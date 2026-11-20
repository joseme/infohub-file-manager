# Crear workspaces faltantes — plan

**Goal:** Que el panel cree en InfoHub el workspace de toda carpeta nueva bajo
`~/Documentos/Infohub`, y avise cuando la API key no puede crearlo.

**Architecture:** Un método nuevo en `InfoHubFileManager` envuelve el filtro de
acceso (`get_accessible_workspace_names`) y crea lo que falta; scan, sort y
sync completo consumen el mismo método. `sync_bot.py` no cambia.

**Tech Stack:** Python 3.12, Flet, requests, pytest.

**Spec:** `docs/superpowers/specs/2026-11-19-crear-workspaces-faltantes-design.md`

## Global Constraints

- ES es la fuente de textos; cada clave nueva va también en EN con los mismos
  campos (`tests/i18n_test.py` lo verifica).
- Simulación (`simular=True`) no escribe en InfoHub.
- No crear workspaces fuera de `allowed_workspaces` ni protegidos.

## Review Focus

- API key sin permiso de creación → la carpeta no aparece y el resultado es
  `warning` con el nombre; no debe romper el resto de la operación.
- Carpeta protegida sin workspace → no se crea nada (se administra fuera).
- Simulación con carpeta nueva → no hay POST.
- Workspace nuevo vacío → aparece en el escaneo con `file_count: 0`.
- Error de red en el POST → aviso, resto de la operación sigue.

---

### Task 1: Crear workspaces faltantes

**Files:**
- Modify: `app.py` (`InfoHubFileManager`, junto a `get_accessible_workspace_names`)
- Modify: `i18n.py` (claves `result.*` en ES y EN)
- Test: `tests/app_test.py` (clase nueva `TestEnsureWorkspaces`)

**Interfaces:**
- Produce: `ensure_workspaces(folder_names: list) -> tuple[set, dict]` →
  `(nombres_accesibles, {carpeta: motivo_del_fallo})`. Añade a los accesibles
  los workspaces que creó.
- Produce: `_creation_warnings(result: dict, avisos: dict) -> dict` → añade
  `message`/`warnings` y pasa `status` a `"warning"` si hay avisos.

- [ ] **Step 1: Tests que fallan** (se crea / 403 avisa / protegido no intenta /
  simulación no crea / scan muestra el nuevo).
- [ ] **Step 2:** `pytest tests/app_test.py -k ensure -v` → FAIL (`AttributeError`).
- [ ] **Step 3:** Implementar `ensure_workspaces`, `_creation_warnings`,
  `_in_scope`, `_create_workspace_remote` y claves i18n.
- [ ] **Step 4:** `pytest -q` → 236+ verdes.
- [ ] **Step 5:** Commit.

### Task 2: Cablear scan / sort / sync completo

**Files:**
- Modify: `app.py` (líneas de filtro en `scan_files`, `sort_files`,
  `full_upload_and_clean`)

**Interfaces:**
- Consume: `ensure_workspaces`, `_creation_warnings` de Task 1.

- [ ] **Step 1:** Reemplazar `get_accessible_workspace_names` por
  `ensure_workspaces` en los tres sitios (en simulación, `_creation_warnings`
  solo si hubo avisos; no crear).
- [ ] **Step 2:** Test de scan con carpeta nueva + POST 201 → aparece.
- [ ] **Step 3:** `pytest -q` → verde.
- [ ] **Step 4:** Commit.
