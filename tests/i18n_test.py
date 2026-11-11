"""Diccionarios de la interfaz (i18n.py) y su uso por sesión."""

import string
from unittest.mock import MagicMock, patch

import i18n
import sync_guards
from demo_mode import DemoSync
from i18n import EN, ES, Translator


def _fields(text):
    return sorted({name for _, name, _, _ in string.Formatter().parse(text) if name})


def test_es_y_en_tienen_las_mismas_claves():
    assert sorted(EN) == sorted(ES)


def test_los_campos_de_formato_coinciden():
    distintos = [k for k in ES if _fields(ES[k]) != _fields(EN[k])]
    assert distintos == []


def test_ningun_texto_vacio():
    assert [k for d in (ES, EN) for k, v in d.items() if not v.strip()] == []


def test_cada_campo_de_configuracion_tiene_etiqueta():
    from config_manager import ConfigManager

    faltan = [f["key"] for f in ConfigManager.get_schema() if f"config.field.{f['key']}" not in ES]
    assert faltan == []


def test_translator():
    en = Translator("en")
    assert en("login.signedIn", user="ana") == "Signed in as ana"
    assert Translator()("login.signedIn", user="ana") == "Sesión iniciada como ana"
    assert Translator("fr").lang == "es"
    assert en.plural("demo.docsInInfohub", 1) == "1 document in InfoHub"
    assert en.plural("demo.docsInInfohub", 3) == "3 documents in InfoHub"
    assert Translator("es").size(1536 * 1024) == "1,5 MB"
    assert en.size(1536 * 1024) == "1.5 MB"
    assert en.size(10) == "1 KB"


def test_resolve_usuario_instancia_espanol():
    assert i18n.resolve("en", "es") == "en"
    assert i18n.resolve(None, "en") == "en"
    assert i18n.resolve(None, None) == "es"
    assert i18n.resolve("fr", "de") == "es"


def _resp(status, body):
    r = MagicMock(status_code=status)
    r.json.return_value = body
    return r


def test_fetch_instance_language():
    with patch("i18n.requests.get", return_value=_resp(200, {"language": "en"})) as get:
        assert i18n.fetch_instance_language("http://ih:3001/") == "en"
        assert get.call_args.args[0] == "http://ih:3001/api/system/instance-language"
    with patch("i18n.requests.get", return_value=_resp(200, {"language": "fr"})):
        assert i18n.fetch_instance_language("http://ih") is None
    with patch("i18n.requests.get", return_value=_resp(404, {})):
        assert i18n.fetch_instance_language("http://ih") is None
    with patch("i18n.requests.get", side_effect=OSError("caído")):
        assert i18n.fetch_instance_language("http://ih") is None
    assert i18n.fetch_instance_language("") is None


def test_mensajes_del_manager_en_ingles(tmp_path):
    from app import InfoHubFileManager

    with patch.dict("os.environ", {"WATCHED_FOLDERS_ROOT": ""}):
        mgr = InfoHubFileManager({"watched_folders_root": ""})
    mgr.tr = Translator("en")
    assert mgr.scan_files()["message"] == "The watched root folder is not configured (WATCHED_FOLDERS_ROOT)"
    mgr.watched_root = str(tmp_path / "nope")
    assert mgr.scan_files()["message"].startswith("The root folder does not exist")


def test_guardas_en_ingles(tmp_path):
    en = Translator("en")
    assert "local folder is empty" in sync_guards.evaluar_borrado(0, 5, 5, tr=en)
    assert "(60 %)" in sync_guards.evaluar_borrado(40, 100, 60, tr=en)
    assert "does not exist" in sync_guards.raiz_accesible(tmp_path / "nope", tr=en)


def test_demo_en_ingles():
    sync = DemoSync("http://ih", "jwt", MagicMock(), Translator("en"))
    with patch.object(sync, "fetch", return_value=None):
        assert sync.simulate("/tmp")["message"] == "Your demo could not be read from InfoHub."
