# Cierre: File Manager en español e inglés

**Fecha:** 2026-11-11 · **Rama:** `feature/i18n`

Con este cambio, todo el ecosistema queda en es/en: InfoHub core (PR #23), Infohub Chat (#14), DMS (#7) y File Manager.

## Qué cambió

- **`i18n.py`:** diccionarios `ES`/`EN`, `Translator` por sesión (texto, plural, tamaños), `fetch_instance_language` y `resolve` (usuario > instancia > es).
- **Manager, demo y guardas del borrado:** sus mensajes de resultado pasan por el `Translator` de la sesión. Antes mezclaban inglés y español. Los mensajes del log no cambian.
- **`app.py`:**
  - `_main` pasó a `_build(page, session)`;
  - la sesión guarda el manager con su token, la configuración, el registro, los totales y el modo demo;
  - cambiar de idioma rearma la pantalla con esa sesión, sin volver a pedir el login;
  - las operaciones se identifican por clave (`scan`, `simulate`…) y ya no por su nombre visible.
- **Selector:** «Español / English» en la barra superior y en el diálogo de inicio de sesión. La elección se guarda en `shared_preferences`.
- **Idioma de la instancia:** se pide en segundo plano al arrancar y otra vez tras el login, por si cambió la URL. Si cambia el idioma visible, la pantalla se rearma.
- **Recorrido** (`tour.js`): pasos y botones en los dos idiomas.
- **Tratamiento:** el español pasó de vos a tú («Accede», «Elige la carpeta»), como en Chat y el DMS.
- **Corrección aparte:** `ConfigManager.get_schema()` devuelve una copia. La prueba que lo exigía pasaba sin probarlo y contaminaba a las demás.

## Verificación

- `pytest`: 233 pruebas, 10 nuevas en `tests/i18n_test.py`.
- Versión web local contra el InfoHub de dev, revisada con Playwright:
  - login en español;
  - cambio a inglés desde el login;
  - inicio de sesión;
  - cambio a español con la sesión iniciada, sin que vuelva a pedir el login;
  - escaneo en español;
  - recarga que conserva la elección;
  - recorrido en inglés;
  - idioma de la instancia guardado en `en` y corregido a `es` cuando respondió InfoHub.

## Pendiente

- Prueba en la app de escritorio (Windows/Linux) y del modo demo con una cuenta de demo.
- `sync_bot.py`, el log y `USER_GUIDE_ES.md` quedan en español.
