# 🔄 Plan de Migración: ManyChat → ChatWoot (Self-hosted)

**Alcance:** Migrar la operación de mensajería de **WhatsApp**, **Instagram DM** y **Messenger (Facebook)** desde ManyChat hacia una instancia **self-hosted de ChatWoot (Docker/VPS)**.

**Fecha:** Septiembre 2026 (rev. 2 — actualizada a ChatWoot v4.18.0, sep 2026) · **Estado:** Propuesto

---

## 1. Resumen ejecutivo

| Aspecto | Decisión |
|---|---|
| Plataforma destino | ChatWoot CE **v4.18.x** self-hosted (Docker en VPS) — versión fija, no `latest` |
| Canales a migrar | WhatsApp Cloud API, Instagram DM, Messenger |
| Datos a migrar | Contactos, etiquetas, campos personalizados |
| Historial de conversaciones | **No migrable** (ManyChat no permite exportarlo en bulk) — ver §4.3. Con coexistencia de WhatsApp el historial de ese canal se preserva en la app del teléfono |
| Cutover | **Sin ventana muerta**: con el modo coexistencia de WhatsApp (v4.5+) el número puede estar conectado a ambas plataformas; fallback a cutover clásico en fin de semana (~2–4 hs) |
| Duración total estimada | **3–4 semanas** (incluye revisión de app de Meta) |

**Motivaciones típicas:** eliminar costo de suscripción de ManyChat (que escala por contactos), liberación de datos (self-hosted), bandeja unificada omnicanal con agentes humanos, y posibilidad de conectar la bandeja con IA propia (ej. AnythingLLM/InfoHub) vía Agent Bot.

---

## 2. Equivalencias ManyChat → ChatWoot

| Concepto ManyChat | Equivalente en ChatWoot | Notas |
|---|---|---|
| Contactos | Contacts | Importados vía API; dedupe por teléfono |
| Etiquetas (Tags) | Labels (etiquetas) | Migrables 1:1 |
| Custom fields (CUF) | Custom attributes | Definir tipos antes de importar |
| Flows / Automation | **No hay equivalente directo** | Reemplazo: Agent Bot (API) + Automation Rules + Campaigns; o bot externo (n8n/Rasa) vía webhooks |
| Keywords / respuestas automáticas | Automation Rules (keyword-based) + Agent Bot | |
| Sequences (mensajes programados) | Campaigns (unicast) | ChatWoot no tiene drip-secuencias nativas — evaluar si se necesita |
| Live chat humano | Bandeja compartida con agentes, roles, asignación | Fortaleza de ChatWoot |
| WhatsApp Business API | Inbox de WhatsApp Cloud API | Mismo número/WABA, se reconecta — ver §5.3 |
| Instagram DM | Inbox Instagram (Business Login) | Requiere app Meta + revisión |
| Messenger (página FB) | Inbox Messenger (Facebook) | Soportado nativamente |
| Webhooks externos | Webhooks de ChatWoot + API | Integraciones similares |

> ⚠️ **La brecha principal es la construcción de flows visuales.** ChatWoot es una plataforma de mensajería con agentes, no un constructor de chatbots. Si los flows de ManyChat son complejos, planificar un bot externo (Fase 5).

> ✅ **Novedad v4.17–v4.18 que beneficia esta migración:** gestión de plantillas de WhatsApp Cloud API y Twilio desde la UI y la API de ChatWoot, seguimiento de entrega de campañas WhatsApp *(Enterprise)*, WhatsApp para contactos solo-BSUID, setup guiado de WhatsApp y métricas de salud del número, plus correcciones del canal Instagram en v4.17.1 (usar ≥ 4.17.1, no 4.17.0).

---

## 3. Arquitectura destino (self-hosted)

```
Internet ──> Nginx (SSL, dominio ej. chat.tudominio.com)
                │
                ├──> ChatWoot rails  (app web + API, :3000)
                ├──> ChatWoot worker (sidekiq, colas/webhooks)
                ├──> PostgreSQL (datos, volumen persistente)
                └──> Redis        (colas + cache)
```

**Requisitos del VPS:** 2 vCPU / 4 GB RAM mínimo (recomendado 4 vCPU / 8 GB si hay 3 canales activos + bot), 40+ GB de disco (adjuntos), Docker 20.10+ y Docker Compose v2, dominio con DNS apuntando al servidor.

**Detalles críticos de la instalación:**
- Imagen `chatwoot/chatwoot:v4.18.0-ce` **fija** (evitar `latest` para reproducibilidad; no usar < 4.17.1 por bugs de Instagram).
- Postgres: verificar la versión soportada por la imagen elegida (14.x en 4.x) y declararla explícita en el compose — nunca usar `postgres:latest`.
- `.env` desde el template oficial (`chatwoot/.env.example`): configurar `FRONTEND_URL=https://chat.tudominio.com`, `FORCE_SSL=true`, `SECRET_KEY_BASE`, y credenciales propias de Postgres/Redis.
- Preparar la base: `docker compose run --rm rails bundle exec rails db:chatwoot_prepare`.
- **Nginx debe tener `underscores_in_headers on;`** (ChatWoot depende de headers con guion bajo) y `client_max_body_size 0;`.
- SSL con certbot/Let's Encrypt — **obligatorio**: los webhooks de Meta exigen HTTPS.
- Volúmenes persistentes para Postgres y `storage/` (adjuntos) + **backups diarios** de la DB (`pg_dump` cron) antes de cada fase.
- Variables de canales (ver Fase 2): `FB_APP_ID`, `FB_APP_SECRET`, token de verificación de Instagram; para Embedded Signup de WhatsApp: `WHATSAPP_EMBEDDED_SIGNUP_CONFIG` y `WHATSAPP_EMBEDDED_SIGNUP_VERIFY_TOKEN`.
- Healthcheck del stack: `curl -f http://localhost:3000/api` dentro de la red interna (alerta temprana sin depender de Nginx).
- Stack recomendado: 2 réplicas de sidekiq desde el día 1; el worker absorbe toda la carga de webhooks, campañas e importaciones.

---

## 4. Inventario y mapeo de datos

### 4.1 Qué se puede exportar de ManyChat

| Dato | Método de exportación | Limitaciones |
|---|---|---|
| Contactos (nombre, teléfono, email) | Google Sheets integration, API (`/fb/subscriber`) o nodo Data Collection | No hay "export all" bulk en la UI; paginar por API |
| Etiquetas (tags) | Por contacto vía API / Sheets | No hay endpoint de volcado global; iterar contactos |
| Custom fields | Igual que contactos | Tipos se pierden: definirlos a mano en ChatWoot |
| Opt-ins de WhatsApp | Campo de suscripción por contacto | Preservar para compliance |
| **Historial de conversaciones** | ❌ **No existe exportación** | Only UI; no API/bulk. Opciones en §4.3 |

> Requiere plan **Pro** de ManyChat para acceso API (token en *Settings → API*).

### 4.2 Mapeo al modelo de ChatWoot

```
ManyChat                          ChatWoot
─────────────────────────────    ─────────────────────────────
contact.phone        ────────>   contact.phone (clave de dedupe)
contact.name         ────────>   contact.name
tag X                ────────>   label "x" (slugificado)
custom field "Plan"  ────────>   custom_attribute "plan"
```

### 4.3 Historial de conversaciones — decisión

Opciones, de menor a mayor esfuerzo:

1. **No migrar (recomendado).** ChatWoot parte con historia limpia. Si un caso requiere contexto, se consulta ManyChat en modo lectura durante los 14 días de paralelismo.
2. **Archivo externo.** Exportar manualmente los chats más importantes (cuenta de soporte) a CSV/PDF como referencia jurídica/comercial.
3. **Sembrar resúmenes en ChatWoot.** Al importar cada contacto, crear una conversación cerrada con nota interna (no mensaje) con el resumen del último ticket. Costo alto de scripting, valor marginal — solo si el negocio lo exige.

**Decisión por defecto: opción 1** — validar con el equipo antes de la Fase 4.

---

## 5. Fases del plan

### Fase 0 — Preparación e inventario (semana 1, 2–3 días)

- [ ] Generar API token de ManyChat (*Settings → API*) — requiere plan Pro.
- [ ] Exportar contactos con teléfono, nombre, email, tags y CUFs (script o Google Sheets integration).
- [ ] Documentar **todos** los flows activos: disparadores (keywords, welcome, respuestas a story/comentarios), condiciones, mensajes, acciones.
- [ ] Inventario de sequences/campaigns activas y fecha de último envío.
- [ ] Definir correspondencia de etiquetas y atributos personalizados (tabla de mapeo §4.2).
- [ ] Listar plantillas de WhatsApp (HSM) aprobadas y sus usos. En ChatWoot ≥ 4.17 se gestionan desde la propia UI/API — simplifica la Fase 3.
- [ ] Cargar balance de mensajes por canal (30–90 días) para dimensionar costos de Cloud API y colas del worker.
- [ ] Identificar en ManyChat: capturas de leads activas, integraciones externas conectadas (Sheets, CRM, webhooks) y automatizaciones de comentarios/respuestas a stories.
- [ ] Congelar cambios en ManyChat (no crear flows nuevos de acá en adelante).
- [ ] Aprovisionar VPS + dominio + DNS.

### Fase 1 — Infraestructura ChatWoot (semana 1–2, 1 día)

- [ ] Desplegar stack Docker compose de producción (rails, 2× sidekiq, postgres con versión fija, redis).
- [ ] Configurar `.env`, ejecutar `db:chatwoot_prepare`, levantar servicios.
- [ ] Nginx + Let's Encrypt, verificar `curl -I https://chat.tudominio.com/api` → 200.
- [ ] Crear usuario super-admin y cuentas de agentes/equipos.
- [ ] Configurar backups automáticos de Postgres y `storage/`.
- [ ] Prueba de humo: bandeja de live-chat widget funciona.

### Fase 2 — App de Meta y webhooks (semana 2, 2–4 días ⚠ incluye revisión)

- [ ] Crear app tipo *Business* en el portal de desarrolladores de Meta.
- [ ] Agregar productos: **Messenger**, **Instagram**.
- [ ] Configurar webhooks: callback `{FRONTEND_URL}/webhooks/instagram` (y el de Messenger), verify token correspondiente, suscripciones `messages`, `messaging_seen`, `message_reactions`, `messaging_postbacks`.
- [ ] Configurar en ChatWoot (`/super_admin/app_config`): `FB_APP_ID`, `FB_APP_SECRET`, token de verificación Instagram/IG.
- [ ] Solicitar permisos avanzados y envío a revisión de Meta (puede tardar días — **arrancar temprano**):
  - `pages_messaging`, `pages_manage_metadata`, `pages_show_list`, `pages_read_engagement`
  - `instagram_manage_messages`, `instagram_basic`, `business_management`
- [ ] Mientras tanto, validar todo con **app de prueba** + cuentas tester (Instagram/Messenger). La revisión de permisos avanza en paralelo sin bloquear el resto del plan.

### Fase 3 — Conexión de canales (semana 2–3)

**3.1 WhatsApp** — el número ya está dado de alta en Meta Cloud API (ManyChat lo usa así):
- [ ] Elegir método de conexión:
  - **A) Coexistencia (recomendado, v4.5+):** desde Embedded Signup con el modo coexistencia se conecta el número real a ChatWoot **sin desconectarlo de ManyChat** — cero ventana muerta y sin plantilla de contingencia. Limitación: los mensajes entrantes llegan a la app webhook-activa (ManyChat), no a ambas. Alternativa sin esta restricción: la app oficial de WhatsApp Business en el teléfono sincroniza el historial y recibe los mensajes mientras ChatWoot envía.
  - **B) Embedded Signup clásico** (sin coexistencia) o **configuración manual** (`phone_number_id`, `waba_id`, token permanente): requiere desconectar ManyChat y conectar ChatWoot en el mismo cutover (Fase 7).
- [ ] En ambos casos, validar primero con un número de prueba.
- [ ] Verificar que las plantillas HSM se resuelven y el envío saliente funciona (recuerda: en ≥ 4.17 se administran desde ChatWoot).

**3.2 Instagram:**
- [ ] Cuenta IG debe ser **professional/business** y vinculada a la página de Facebook.
- [ ] Usar **Instagram Business Login** (método recomendado; el login vía Facebook está deprecado desde v4.1). Configurar redirect `{FRONTEND_URL}/instagram/callback` en la app Meta.
- [ ] Crear inbox Instagram en ChatWoot y validar con cuenta tester (usar ≥ 4.17.1: corrige login IG y mensajes duplicados de Facebook).

**3.3 Messenger:**
- [ ] Crear inbox tipo Messenger en ChatWoot → login con Facebook → seleccionar página.
- [ ] Validar recepción/respuesta con tester.

### Fase 4 — Importación de datos (semana 3, 1 día)

- [ ] Crear en ChatWoot las labels y custom attributes según el mapeo.
- [ ] Script de importación (Python, igual stack del repo):
  - `POST /api/v1/accounts/{id}/contacts` con `name`, `phone`, `email`, `custom_attributes` y `labels`.
  - Dedupe previo por teléfono (ChatWoot también busca por phone — reutilizar GET de search antes de crear).
  - Rate-limit amable (p. ej. 5 req/s) y log de errores para reintento.
- [ ] **Piloto: importar 50 contactos**, validar en UI (atributos, labels, búsqueda).
- [ ] Importación completa + conteo de verificación (importados = exportados − duplicados).

### Fase 5 — Automatización y bot (semana 3, 2–3 días)

Elegir según complejidad de los flows inventariados:

| Escenario | Solución |
|---|---|
| Flows simples (bienvenida, keywords, menú 1 nivel) | Automation Rules + respuestas guardadas (canned responses) de ChatWoot |
| Flows medianos (formularios, condiciones) | **Agent Bot** nativo vía API (`agent_bots`, webhook de bot con handoff a agentes) |
| Flows complejos (drip campaigns, pagos, IA) | Bot externo (n8n / Rasa / script propio) conectado a los webhooks + API de ChatWoot |

- [ ] Re-implementar los flows del inventario de Fase 0 en el escenario elegido.
- [ ] Definir reglas de handoff: horarios, asignación por equipo, SLA de primera respuesta.
- [ ] Si aplica: conectar el bot con AnythingLLM/InfoHub para respuestas con IA sobre los documentos (oportunidad nueva que ManyChat no tenía).

### Fase 6 — Pruebas QA (semana 3, 1 día)

Checklist por canal — probar en producción con testers:
- [ ] WhatsApp: mensaje entrante/saliente, media (img/pdf), plantilla HSM, emoji/acentos, conversation status (open/resolved), handoff a agente.
- [ ] Instagram: DM entrante/saliente, media, comentario→DM si se usaba, historial visible en bandeja.
- [ ] Messenger: mensaje entrante/saliente, postback de menú persistente, media.
- [ ] Transversal: labels automáticas, asignación, notas internas, notificaciones de agentes, horas fuera de servicio.
- [ ] Bot: cada flow del inventario dispara y termina como se espera; escalado a humano funciona.
- [ ] Búsqueda de contacto importado + atributos correctos.

### Fase 7 — Cutover (ventana recomendada: fin de semana)

1. [ ] Comunicar a clientes activos (plantilla WhatsApp) el cambio si aplica.
2. [ ] **Pausar** (no borrar) flows y sequences en ManyChat.
3. [ ] WhatsApp — según método elegido en Fase 3.1:
   - **Coexistencia:** el número ya está conectado desde la Fase 3; aquí solo se desconecta ManyChat cuando la operación en ChatWoot esté validada (idealmente ≥ 48 hs antes).
   - **Clásico:** desconectar el número de ManyChat y conectarlo en ChatWoot en la misma ventana ( minutos–horas sin servicio).
4. [ ] Verificar webhooks OK y mensajes fluyendo en la bandeja.
5. [ ] Verificar Instagram y Messenger en ChatWoot (desconectar de ManyChat al confirmar).
6. [ ] Prueba end-to-end de los 3 canales (envío y recepción).
7. [ ] Import final de contactos delta (los creados entre la Fase 4 y hoy).
8. [ ] Monitoreo activo 24–48 hs (logs del worker, cola de sidekiq, bandeja).

**Rollback:** ManyChat sigue activo (pausado, no cancelado) durante 14 días. Revertir = reanudar flows y reconectar canales en ManyChat (~30 min).

### Fase 8 — Post-migración (semanas 4–6)

- [ ] Semana 1: revisión diaria de bandeja, errores de webhook y latencia del bot.
- [ ] Ajustar reglas de automatización según casos reales no cubiertos.
- [ ] Medir: tiempo de primera respuesta, resolución, volumen por canal (vs. métricas de ManyChat).
- [ ] Día 14: **cancelar suscripción de ManyChat** y revocar tokens.
- [ ] Documentar en el repo la configuración final (`.env` de referencia, runbook de actualización: `docker compose pull` + `db:chatwoot_prepare`).

---

## 6. Riesgos y mitigaciones

| Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|
| Revisión de app de Meta se demora/rechaza | Alta | Bloquea IG/Messenger en producción | Empezar Fase 2 en semana 1; probar con app de prueba mientras tanto |
| El número de WhatsApp no puede estar en ambas plataformas a la vez | ~~Certain~~ **Baja** con coexistencia (v4.5+) | Ventana sin servicio de minutos–horas | Método A (coexistencia) elimina la ventana muerta; si se usa método B, cutover en fin de semana + plantilla de contingencia + número de test |
| Flows de ManyChat no replicables nativamente en ChatWoot | Alta | Pérdida de automatización | Inventario temprano (Fase 0); decidir Agent Bot vs bot externo antes de Fase 5 |
| Historial de conversaciones no migrable | Certain | Los agentes parten sin contexto | Decisión documentada (§4.3); ManyChat en lectura 14 días |
| Sequences/drip no existen en ChatWoot | Alta | Pérdida de re-engagement | Migrar a Campaigns o mantener herramienta de email/CRM para eso |
| Pérdida de adjuntos al self-hostear | Baja | Datos | Volúmenes persistentes + backups diarios desde Fase 1 |
| Rate limits en importación masiva | Media | Import lento o errores | Chunking, reintentos, log de fallos, piloto de 50 primero |
| Equipos no adoptan la nueva bandeja | Media | Retorno a ManyChat | Capacitación en Fase 6, período de paralelismo, soporte interno |

---

## 7. Checklist de cutover (resumen rápido)

```
□ Pausar flows ManyChat
□ WhatsApp (coexistencia): solo desconectar ManyChat tras validar 48 hs en ChatWoot
□ WhatsApp (clásico): desconectar de ManyChat → conectar en ChatWoot → verificar webhook
□ Desconectar IG/Messenger de ManyChat (tras confirmar ChatWoot)
□ E2E de 3 canales OK
□ Import delta de contactos
□ Monitoreo 48 hs
```

---

## 8. Cronograma resumido

| Semana | Fase | Hitos |
|---|---|---|
| 1 | F0 + F1 (+ F2 en paralelo) | Export de datos listo; ChatWoot desplegado; app Meta enviada a revisión |
| 2 | F2 + F3 | Permisos Meta aprobados; canales conectados en test; WhatsApp en coexistencia operativo |
| 3 | F4 + F5 + F6 | Contactos importados; bot funcionando; QA completo |
| 4 | F7 + F8 | Cutover de bajo riesgo (desconexión de ManyChat validada); monitoreo y ajustes; baja de ManyChat día 14 |
