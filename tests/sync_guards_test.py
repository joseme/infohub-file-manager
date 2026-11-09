"""Guardas contra borrados masivos (sync_guards.py) y su uso en sync_bot y app."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import sync_bot
import sync_guards
from app import InfoHubFileManager
from workspace_map import slug_naive


# ---------------------------------------------------------------------------
# evaluar_borrado


class TestEvaluarBorrado:
    def test_sin_huerfanos_permite(self):
        assert sync_guards.evaluar_borrado(0, 0, 0) is None
        assert sync_guards.evaluar_borrado(0, 50, 0) is None

    def test_carpeta_vacia_bloquea_aunque_sea_un_solo_documento(self):
        motivo = sync_guards.evaluar_borrado(locales=0, remotos=1, huerfanos=1)
        assert motivo and "vacía" in motivo

    def test_caida_total_bloquea(self):
        assert sync_guards.evaluar_borrado(0, 300, 300)

    def test_caida_del_60_por_ciento_bloquea(self):
        motivo = sync_guards.evaluar_borrado(locales=40, remotos=100, huerfanos=60)
        assert motivo and "60 %" in motivo

    def test_por_debajo_del_umbral_permite(self):
        assert sync_guards.evaluar_borrado(locales=60, remotos=100, huerfanos=40) is None

    def test_justo_en_el_umbral_permite(self):
        # reorganizar un workspace entero deja 50 % viejos + 50 % nuevos
        assert sync_guards.evaluar_borrado(locales=50, remotos=100, huerfanos=50) is None

    def test_pocos_huerfanos_se_borran_aunque_sean_mayoria(self):
        # workspace pequeño: 3 de 4 documentos, por debajo del mínimo absoluto
        assert sync_guards.evaluar_borrado(locales=1, remotos=4, huerfanos=3) is None

    def test_umbral_y_minimo_configurables(self):
        assert sync_guards.evaluar_borrado(80, 100, 20, umbral_pct=10)
        assert sync_guards.evaluar_borrado(1, 4, 3, minimo=0)


# ---------------------------------------------------------------------------
# montaje_caido / raiz_accesible


class TestMontajes:
    def test_sin_montajes_requeridos(self, tmp_path):
        assert sync_guards.montaje_caido(tmp_path, []) is False
        assert sync_guards.montaje_caido(tmp_path, None) is False

    def test_carpeta_requerida_no_montada(self, tmp_path):
        assert sync_guards.montaje_caido(tmp_path, [str(tmp_path)]) is True

    def test_subcarpeta_de_un_montaje_caido(self, tmp_path):
        sub = tmp_path / "Legal" / "contratos"
        sub.mkdir(parents=True)
        assert sync_guards.montaje_caido(sub, [str(tmp_path / "Legal")]) is True

    def test_montaje_ajeno_no_afecta(self, tmp_path):
        (tmp_path / "A").mkdir()
        (tmp_path / "B").mkdir()
        assert sync_guards.montaje_caido(tmp_path / "A", [str(tmp_path / "B")]) is False

    def test_montaje_activo(self, tmp_path):
        with patch("sync_guards.os.path.ismount", return_value=True):
            assert sync_guards.montaje_caido(tmp_path, [str(tmp_path)]) is False

    def test_raiz(self, tmp_path):
        assert sync_guards.raiz_accesible(tmp_path) is None
        assert "no existe" in sync_guards.raiz_accesible(tmp_path / "nope")
        with patch("sync_guards.os.listdir", side_effect=OSError("Host is down")):
            assert "no es accesible" in sync_guards.raiz_accesible(tmp_path)


# ---------------------------------------------------------------------------
# estado de fuentes externas


ESTADO_FUENTES = {
    "sharepoint": {"01ABC": {"slug": "ws", "remote_name": "contrato.pdf"},
                   "01DEF": {"slug": "otro", "remote_name": "ajeno.pdf"}},
    "zoho": {"desk:1:2": {"slug": "ws", "remote_name": "ticket-12.pdf"}},
    "_meta": {"sharepoint": {"delta_link": "x"}},
}


class TestFuentesExternas:
    def test_nombres_por_slug(self):
        assert sync_guards.nombres_externos("ws", ESTADO_FUENTES) == {"contrato.pdf", "ticket-12.pdf"}
        assert sync_guards.nombres_externos("nadie", ESTADO_FUENTES) == set()
        assert sync_guards.nombres_externos("ws", {}) == set()

    def test_quitar_externos(self):
        res = sync_guards.quitar_externos(["contrato.pdf", "viejo.pdf"], {"contrato.pdf"},
                                          sync_bot.coincide_remoto)
        assert res == ["viejo.pdf"]

    def test_cargar_inexistente_o_corrupto(self, tmp_path):
        assert sync_guards.cargar_estado_fuentes(tmp_path / "no.json") == {}
        roto = tmp_path / "roto.json"
        roto.write_text("{no es json")
        assert sync_guards.cargar_estado_fuentes(roto) == {}
        lista = tmp_path / "lista.json"
        lista.write_text("[1, 2]")
        assert sync_guards.cargar_estado_fuentes(lista) == {}

    def test_cargar_valido(self, tmp_path):
        ruta = tmp_path / "estado_fuentes.json"
        ruta.write_text(json.dumps(ESTADO_FUENTES))
        assert sync_guards.cargar_estado_fuentes(ruta) == ESTADO_FUENTES


# ---------------------------------------------------------------------------
# sync_bot.sincronizar_carpeta


def _bot_cfg(**extra):
    cfg = dict(sync_bot.DEFAULTS_BOT)
    cfg.update({"borrar_huerfanos": True, "crear_workspaces": False})
    cfg.update(extra)
    return cfg


def _mgr(remotos):
    mgr = MagicMock()
    mgr.protected_workspaces = set()
    mgr.is_protected.return_value = False
    mgr.get_accessible_workspace_names.return_value = ["ws"]
    mgr.get_workspace_documents.return_value = {
        "base_names": set(remotos),
        "doc_names": {b: f"ws/{b}.json" for b in remotos},
    }
    mgr._rel_path.side_effect = lambda f, c: Path(f).relative_to(c).as_posix()
    mgr._remote_name.side_effect = lambda rel: rel.replace("/", "__")
    mgr.delete_documents.side_effect = lambda paths: (True, len(paths), [])
    mgr._update_embeddings.return_value = True
    return mgr


def _carpeta(tmp_path, n):
    carpeta = tmp_path / "ws"
    carpeta.mkdir()
    for i in range(n):
        (carpeta / f"f{i}.txt").write_text(str(i))
    return carpeta


def _sync(mgr, carpeta, cfg, estado_fuentes=None, dry=False):
    resolver = MagicMock()
    resolver.slug.return_value = ("ws", True)
    return sync_bot.sincronizar_carpeta(mgr, resolver, carpeta, cfg, {}, dry, 0, [10 ** 9],
                                        estado_fuentes)


class TestSyncBotGuardas:
    def test_carpeta_vacia_no_borra(self, tmp_path):
        mgr = _mgr([f"f{i}.txt" for i in range(30)])
        res = _sync(mgr, _carpeta(tmp_path, 0), _bot_cfg())
        assert len(res["huerfanos"]) == 30
        assert "vacía" in res["borrado_bloqueado"]
        mgr.delete_documents.assert_not_called()

    def test_caida_parcial_no_borra(self, tmp_path):
        # el montaje solo devolvió 4 de 30 archivos
        mgr = _mgr([f"f{i}.txt" for i in range(30)])
        res = _sync(mgr, _carpeta(tmp_path, 4), _bot_cfg())
        assert len(res["huerfanos"]) == 26
        assert res["borrado_bloqueado"]
        mgr.delete_documents.assert_not_called()

    def test_limpieza_normal_borra(self, tmp_path):
        mgr = _mgr([f"f{i}.txt" for i in range(25)])
        res = _sync(mgr, _carpeta(tmp_path, 20), _bot_cfg())
        assert "borrado_bloqueado" not in res
        assert res["borrados"] == 5
        assert sorted(mgr.delete_documents.call_args.args[0]) == sorted(
            f"ws/f{i}.txt.json" for i in range(20, 25))

    def test_forzar_borrado_salta_la_guarda_de_umbral(self, tmp_path):
        mgr = _mgr([f"f{i}.txt" for i in range(30)])
        res = _sync(mgr, _carpeta(tmp_path, 4), _bot_cfg(forzar_borrado=True))
        assert "borrado_bloqueado" not in res
        assert res["borrados"] == 26

    def test_montaje_caido_bloquea_incluso_forzando(self, tmp_path):
        mgr = _mgr([f"f{i}.txt" for i in range(25)])
        carpeta = _carpeta(tmp_path, 20)
        res = _sync(mgr, carpeta, _bot_cfg(forzar_borrado=True, montajes_requeridos=[str(carpeta)]))
        assert "montajes_requeridos" in res["borrado_bloqueado"]
        mgr.delete_documents.assert_not_called()

    def test_sin_borrar_huerfanos_no_evalua(self, tmp_path):
        mgr = _mgr([f"f{i}.txt" for i in range(30)])
        res = _sync(mgr, _carpeta(tmp_path, 0), _bot_cfg(borrar_huerfanos=False))
        assert "borrado_bloqueado" not in res
        mgr.delete_documents.assert_not_called()

    def test_documentos_de_fuentes_externas_no_son_huerfanos(self, tmp_path):
        remotos = [f"f{i}.txt" for i in range(3)] + ["contrato.pdf", "viejo.pdf"]
        mgr = _mgr(remotos)
        res = _sync(mgr, _carpeta(tmp_path, 3), _bot_cfg(), estado_fuentes=ESTADO_FUENTES)
        assert res["huerfanos"] == ["viejo.pdf"]
        mgr.delete_documents.assert_called_once_with(["ws/viejo.pdf.json"])

    def test_dry_run_bloqueado_tampoco_borra(self, tmp_path):
        mgr = _mgr([f"f{i}.txt" for i in range(30)])
        res = _sync(mgr, _carpeta(tmp_path, 0), _bot_cfg(), dry=True)
        assert res["borrado_bloqueado"]
        mgr.delete_documents.assert_not_called()


# ---------------------------------------------------------------------------
# app.InfoHubFileManager.full_upload_and_clean


@pytest.fixture
def mgr_app(tmp_path):
    with patch.dict(os.environ, {"ANYTHINGLLM_API_KEY": "", "ANYTHINGLLM_BASE_URL": "",
                                 "WATCHED_FOLDERS_ROOT": "", "PROTECTED_WORKSPACES": ""}):
        mgr = InfoHubFileManager(config={"anythingllm_api_key": "k",
                                         "anythingllm_base_url": "http://infohub.test",
                                         "watched_folders_root": str(tmp_path)})
    return mgr


def _arbol(tmp_path, n):
    ws = tmp_path / "Infohub" / "WS"
    ws.mkdir(parents=True)
    for i in range(n):
        (ws / f"f{i}.txt").write_text(str(i))
    return ws


def _full(mgr, remotos, simular=False):
    docs = {"base_names": set(remotos), "doc_names": {b: f"ws/{b}.json" for b in remotos},
            "raw_docs": [], "exists": True}
    with patch.object(mgr, "get_accessible_workspace_names", side_effect=lambda n: n), \
         patch.object(mgr, "get_workspace_slug", side_effect=slug_naive), \
         patch.object(mgr, "get_workspace_documents", return_value=docs), \
         patch.object(mgr, "delete_documents", side_effect=lambda p: (True, len(p), [])) as m_del, \
         patch.object(mgr, "upload_file_to_workspace", return_value=(False, True, "ya existe")), \
         patch.object(mgr, "file_exists_in_workspace", return_value=True), \
         patch.object(mgr, "_update_embeddings", return_value=True):
        res = mgr.full_upload_and_clean(simular=simular)
    return res, m_del


class TestAppGuardas:
    def test_carpeta_vacia_no_borra(self, mgr_app, tmp_path):
        _arbol(tmp_path, 0)
        res, m_del = _full(mgr_app, [f"f{i}" for i in range(15)])
        m_del.assert_not_called()
        assert res["status"] == "warning"
        assert "WS" in res["blocked_deletions"]
        assert "Borrado bloqueado por seguridad" in res["message"]

    def test_caida_parcial_no_borra(self, mgr_app, tmp_path):
        _arbol(tmp_path, 2)
        res, m_del = _full(mgr_app, [f"f{i}" for i in range(20)])
        m_del.assert_not_called()
        assert res["deleted"] == 0

    def test_limpieza_normal_borra(self, mgr_app, tmp_path):
        _arbol(tmp_path, 18)
        res, m_del = _full(mgr_app, [f"f{i}" for i in range(20)])
        assert res["deleted"] == 2
        assert res["blocked_deletions"] == {}
        assert res["status"] == "success"

    def test_montaje_caido(self, mgr_app, tmp_path):
        ws = _arbol(tmp_path, 18)
        mgr_app.montajes_requeridos = [str(ws)]
        res, m_del = _full(mgr_app, [f"f{i}" for i in range(20)])
        m_del.assert_not_called()
        assert "montajes_requeridos" in res["blocked_deletions"]["WS"]

    def test_umbral_desde_config(self, tmp_path):
        with patch.dict(os.environ, {"WATCHED_FOLDERS_ROOT": "", "PROTECTED_WORKSPACES": ""}):
            mgr = InfoHubFileManager(config={"umbral_borrado_pct": 90, "minimo_borrado": 0,
                                             "montajes_requeridos": ["/mnt/nas"]})
        assert (mgr.umbral_borrado_pct, mgr.minimo_borrado, mgr.montajes_requeridos) == (90, 0, ["/mnt/nas"])

    def test_simulacion_marca_bloqueo_y_no_lo_cuenta(self, mgr_app, tmp_path):
        _arbol(tmp_path, 0)
        res, m_del = _full(mgr_app, [f"f{i}" for i in range(15)], simular=True)
        m_del.assert_not_called()
        assert res["would_delete"] == 0
        assert res["simulation"]["WS"]["borrado_bloqueado"]
        assert len(res["simulation"]["WS"]["huerfanos"]) == 15

    def test_fuentes_externas_no_son_huerfanos(self, mgr_app, tmp_path, monkeypatch):
        _arbol(tmp_path, 3)
        ruta = tmp_path / "estado_fuentes.json"
        ruta.write_text(json.dumps({"sharepoint": {
            "01ABC": {"slug": slug_naive("WS"), "remote_name": "contrato.pdf"}}}))
        monkeypatch.setattr(sync_guards, "ESTADO_FUENTES", ruta)
        res, m_del = _full(mgr_app, ["f0", "f1", "f2", "contrato", "viejo"])
        m_del.assert_called_once_with(["ws/viejo.json"])
        assert res["deleted"] == 1

    def test_raiz_inaccesible(self, mgr_app, tmp_path):
        _arbol(tmp_path, 1)
        with patch("sync_guards.os.listdir", side_effect=OSError("Host is down")):
            res = mgr_app.full_upload_and_clean()
        assert res["status"] == "error"
        assert "no es accesible" in res["message"]
