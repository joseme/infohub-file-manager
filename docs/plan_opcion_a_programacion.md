# Plan: Programación periódica — Opción A (cron + `sync_bot.py` + UI de estado/disparo)

Plan de implementación de la **Opción A** del análisis de alternativas
(`docs/analisis_ui_fuentes_externas.md` no aplica; ver análisis entregado en chat /
resumen aquí): mantener el cron del sistema como motor de ejecución periódica y
hacer que la UI de InfoHub File Manager **consulte su estado y pueda disparar una
corrida**, sin reimplementar ningún scheduler dentro de la app.

## 1. Objetivo

- Que el panel muestre **cuándo fue la última sincronización programada**, con su
  resultado (subidos/actualizados/huérfanos/errores), sin abrir `logs/` a mano.
- Que el panel permita **«Ejecutar ahora»** (corrida completa o dry-run), con el
  mismo motor (`sync_bot.py`), mismos locks y mismo resumen por Telegram.
- Que la instalación/actualización del cron quede **versionada en el repo** y sea
  instalable con un script, en vez de un `crontab.txt` documentado a mano.

## 2. Fuera de alcance (lo que NO hace esta opción)

- **No** añade ningún scheduler dentro de la app (ni APScheduler ni hilos-daemon):
  si la máquina está apagada a la hora programada, no se ejecuta — es la
  limitación aceptada de la Opción A.
- **No** modifica la lógica de sincronización de `sync_bot.py` / `app.py`
  (subida, borrado, embeddings, estado).
- **No** configura fuentes externas nuevas (SharePoint, correo, Zoho…): eso está
  en `docs/analisis_ui_fuentes_externas.md`.
- **No** toca el modo demo ni el tour.
- El borrado de huérfanos **nunca** se programa en automático; sigue siendo la
  corrida separada del domingo 07:30 (`--borrar-huerfanos`).

## 3. Estado actual (punto de partida)

- `sync_bot.py`: CLI headless, reutiliza `InfoHubFileManager`. Lock propio
  (`logs/sync_bot.lock`, `flock`), espera locks de los bots de normativa,
  estado en `logs/estado_sync.json`, log por corrida `logs/sync_*.log`,
  resumen por Telegram. Salida `0` ok / `1` con errores / `2` error de setup.
- `crontab.txt`: líneas del usuario (domingos 06:30 subida, 07:30 borrado de
  huérfanos), referenciadas desde el README.
- `logs/cron.log`: stdout/stderr de cron (sin estructura fiable para parsear).
- UI Flet (`app.py`): no sabe nada de la programación; las operaciones solo se
  disparan con las tarjetas, con `is_processing` como guarda en proceso.
- Distribución: desktop (`build.spec`, PyInstaller, `app.py` como único entry)
  **y** servidor Docker (`Dockerfile`/`docker-compose.yml`, `restart:
  unless-stopped`, sin cron dentro del contenedor).

## 4. Diseño

Tres piezas, todas pequeñas:

### 4.1 `sync_bot.py` escribe un resumen estructurado

Al final de `main()` (tras el resumen por Telegram), escribir
`logs/ultima_sync.json`:

```json
{
  "inicio": "2026-11-08T06:30:01",
  "fin": "2026-11-08T06:41:12",
  "duracion_seg": 671,
  "dry_run": false,
  "borrar_huerfanos": false,
  "totales": {"subidos": 12, "actualizados": 3, "omitidos": 540, "errores": 0},
  "carpetas": [{"carpeta": "odoo", "slug": "odoo17", "subidos": 4, "errores": []}],
  "ok": true
}
```

- Reutiliza los `resultados` que ya se construyen para el resumen: es un
  `json.dump` de lo que ya existe en memoria, no datos nuevos.
- Escritura atómica (tmp + `os.replace`) para que la UI nunca lea un archivo a
  medias.
- `ok = (errores == 0)`. El `dry_run` y `borrar_huerfanos` quedan reflejados
  para que la UI distinga una corrida de simulación de una real.
- Cambio estimado: ~20 líneas en `main()` de `sync_bot.py`. Sin romper CLI,
  flags ni el formato de `logs/sync_*.log`.

### 4.2 La UI muestra el estado (sección «Sincronización programada»)

Sección nueva en el dashboard **o** bloque dentro del diálogo de configuración
(decisión recomendada: bloque propio en el dashboard, visible sin abrir ⚙):

- Lee `logs/ultima_sync.json` al arrancar y tras cada «Actualizar Estado"
  (botón ya existente en el AppBar): «Última ejecución: dom 08-11 06:30 ·
  671 s · 12 subidos, 3 actualizados · ✓ sin errores» / «⚠ 2 errores» /
  «Aún no hay ejecuciones registradas».
- «Próxima ejecución: domingo 06:30» como **texto informativo** desde un nuevo
  campo de config `schedule_info` (text, p. ej. `"domingos 06:30"`), no se
  calcula desde crontab (parsear crontab es frágil y multiplataforma).
  Alternativa honesta: omitir «próxima» y dejar solo «Última».
- Detalle por carpeta bajo un expander (lista ya formateada, misma info que
  el resumen de Telegram).
- Si el archivo no existe o está corrupto: texto neutro, sin excepciones.

### 4.3 «Ejecutar ahora» desde la UI

- Botón en la misma sección, con checkbox «Simulación (dry-run)».
- **No-frozen** (`sys.executable` = python del venv):
  `subprocess.Popen([sys.executable, str(BASE_DIR / "sync_bot.py"), *flags])`
  con `--sin-esperar-locks` opcional. La salida va al panel de logs (lectura
  línea a línea en un hilo) y al terminar se refresca `ultima_sync.json` y las
  stats. El lock `logs/sync_bot.lock` que ya existe impide solapes con la
  corrida de cron; si está ocupado, `sync_bot.py` ya imprime "Ya hay una
  sincronización en curso" y sale — la UI muestra ese mensaje tal cual.
- **Frozen** (PyInstaller, `sys.frozen`): no se puede re-invocar `python
  sync_bot.py` (el .exe *es* la app). Dos caminos, elegir en implementación:
  a) incluir `sync_bot.py` como segundo `EXE` en `build.spec` y ejecutarlo; o
  b) refactor mínimo de `sync_bot.main()` extrayendo `run(bot_cfg, args)`
     importable, y la UI lo llama en un `threading.Thread` (sin subprocess).
     (b) es menos packaging y funciona igual en ambos modos → **recomendado**.
- La operación usa el mismo patrón que las existentes: guarda `is_processing`
  / nuevo guard propio `sync_running`, `show_progress` con `progress_dialog`,
  errores como snackbar, éxito con `show_snackbar` + `add_log`.
- «Simulación (dry-run)» pasa `--dry-run` / `dry=True`: la UI debe etiquetar
  el resultado como simulación (el JSON ya lleva `dry_run`).

### 4.4 Instalación del cron versionada

- `scripts/instalar_cron.sh`: idempotente — lee `crontab.txt`, lo instala con
  `crontab crontab.txt` (o lo fusiona con el crontab actual del usuario en
  vez de sobrescribirlo: `crontab -l`, filtrar las líneas propias por un
  marcador `# infohub-file-manager`, reemplazar, reinstalar).
- Añadir el marcador en `crontab.txt` para poder actualizarlo sin tocar
  entradas ajenas del usuario.
- Documentar en README (sección «Bot de sincronización»): instalar con
  `scripts/instalar_cron.sh`, desinstalar borrando las líneas marcadas.
- Windows/desktop: documentar la alternativa (Programador de tareas con
  `sync_bot.py` + `venv\Scripts\python.exe`, o el .exe) sin automatizarla.

## 5. Fases y archivos

| Fase | Contenido | Archivos |
|---|---|---|
| 1 | Resumen estructurado + lectura en UI | `sync_bot.py` (+`json.dump` en `main`), `app.py` (loader + sección dashboard) |
| 2 | «Ejecutar ahora» (dry-run incluido) | `sync_bot.py` (extraer `run()`), `app.py` (botón + hilo + guardas), `config.json`/`FIELDS_SCHEMA` no se toca salvo `schedule_info` (opcional, texto informativo) |
| 3 | Instalación cron versionada + docs | `crontab.txt` (marcadores), `scripts/instalar_cron.sh`, `README.md` |
| 4 | Tests | `tests/test_ultima_sync.py`, ajuste de tests existentes si los hay |

Estimación: Fase 1 ≈ 1–2 h; Fase 2 ≈ 2–3 h; Fase 3 ≈ 1 h; Fase 4 ≈ 1 h.

## 6. Tests

- `test_ultima_sync.py`:
  - JSON válido → parseo y formato del texto de la UI (helper
    `format_ultima_sync(dict) -> str`, testeable sin Flet).
  - JSON inexistente/corrupto/parcial → texto neutro, sin excepción.
  - Escritura atómica: el lector nunca ve JSON truncado.
- Fase 2: `run()` con `--dry-run` contra un `root` temporal y un
  `InfoHubFileManager` apuntando a un servidor falso (mock de `requests`) o,
  como mínimo, el camino de guarda (`sync_running=True` → botón no dispara).
- `pytest` según `pytest.ini`; no tocar tests existentes.

## 7. Riesgos y mitigaciones

- **Doble ejecución cron + «Ejecutar ahora»**: el lock de `sync_bot.py` es la
  única barrera — no relajarlo; el mensaje «Ya hay una sincronización en
  curso» debe llegar al usuario tal cual (snackbar, no silencio).
- **Frozen sin (a) ni (b)**: si se elige subprocess naíf, el .exe se relanza a
  sí mismo → bug visible. Resolver con (b) recomendado.
- **En web (Docker) sin cron**: «Ejecutar ahora» funciona igualmente; «última
  ejecución» mostrará lo que pasó en el contenedor (o nada, si solo cron del
  host — entonces la UI debe decir «ejecutada por cron del host; ver logs/»).
  Decidir en Fase 3 si el contenedor lleva cron o se documenta el del host.
- **`cron.log` sin rotación**: no es parte de este plan, pero anotarlo.
- **`ultima_sync.json` con datos del pasado tras cambiar carpetas**: mostrar
  siempre la fecha junto al resumen; no ocultar.
- **Secretos**: la UI solo lee el resumen; nunca volcar config ni tokens al
  panel de logs en la corrida disparada desde el botón.

## 8. Criterios de aceptación

1. Tras una corrida (cron o botón), el dashboard muestra fecha, duración y
   totales correctos; sin corridas aún, muestra un estado neutro.
2. «Simulación (dry-run)» no sube ni borra nada y lo indica.
3. Con una sincronización en curso, el botón no dispara otra.
4. `scripts/instalar_cron.sh` instalado dos veces no duplica ni borra entradas
   ajenas del crontab del usuario.
5. Suite `pytest` en verde.

## 9. Pendientes / decisiones

- ¿Sección propia en el dashboard o bloque en el diálogo de configuración?
  (recomendado: dashboard, sin abrir ⚙)
- ¿Mostrar «próxima ejecución» (campo informativo) o solo «última»?
- ¿Contenedor Docker con cron/supercronic o cron del host documentado?
- Fase 2: (a) segundo EXE o (b) `run()` importable (recomendado b).
