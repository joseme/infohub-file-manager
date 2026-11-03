"""Modo demo: carpeta del prospecto <-> workspaces de su demo en InfoHub."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from app import InfoHubFileManager
from demo_mode import DemoSync, folder_name, format_mb, is_document

BASE = "https://demo.infohub.example.com"
MB = 1024 * 1024


def _response(status=200, body=None):
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status
    resp.json.return_value = body if body is not None else {}
    return resp


def _demo(**overrides):
    demo = {
        "company": "ACME",
        "industry": "juridica",
        "expiresAt": "2099-01-01T00:00:00Z",
        "maxDocs": 20,
        "usedDocs": 1,
        "maxBytes": 50 * MB,
        "usedBytes": 1000,
        "workspaces": [
            {
                "slug": "contratos",
                "name": "Contratos",
                "documents": [
                    {
                        "docId": "d-1",
                        "title": "Sub__informe.pdf",
                        "filename": "Sub__informe.pdf-0f4c2a9e-1b2c-4d5e-8f90-123456789abc.json",
                        "bytes": 1000,
                        "createdAt": "2026-11-03T10:00:00Z",
                    }
                ],
            },
            {"slug": "expedientes", "name": "Expedientes", "documents": []},
        ],
        "username": "ana",
        "fileManagerUrl": None,
        "serverUrl": None,
    }
    demo.update(overrides)
    return demo


@pytest.fixture
def matcher():
    with patch("requests.get", return_value=_response(500)):
        return InfoHubFileManager(config={"anythingllm_api_key": "", "anythingllm_base_url": BASE})


@pytest.fixture
def sync(matcher):
    return DemoSync(BASE, "jwt-demo", matcher)


def _write(path, content=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_nombre_de_carpeta_valido_en_windows():
    assert folder_name("Catálogo y precios") == "Catálogo y precios"
    assert folder_name('Ventas: "2026"/Q1') == "Ventas- -2026--Q1"
    assert folder_name(" . ") == "workspace"


def test_tamanos_legibles():
    assert format_mb(339) == "1 KB"
    assert format_mb(300 * 1024) == "300 KB"
    assert format_mb(50 * MB) == "50,0 MB"
    assert format_mb(0) == "0,0 MB"


def test_ignora_temporales_y_archivos_del_sistema(tmp_path):
    assert is_document(tmp_path / "contrato.pdf")
    assert not is_document(tmp_path / "~$contrato.docx")
    assert not is_document(tmp_path / ".DS_Store")
    assert not is_document(tmp_path / "Thumbs.db")


def test_crea_una_subcarpeta_por_workspace(sync, tmp_path):
    base = tmp_path / "Mi demo"
    folders = sync.ensure_folders(str(base), _demo())
    assert [f.name for f in folders] == ["Contratos", "Expedientes"]
    assert all(f.is_dir() for f in folders)
    # Repetirlo no falla ni toca lo que ya hay.
    _write(base / "Contratos" / "a.pdf")
    sync.ensure_folders(str(base), _demo())
    assert (base / "Contratos" / "a.pdf").exists()


def test_lee_la_demo_con_la_sesion_y_no_con_la_api_key(sync):
    with patch("requests.get", return_value=_response(200, {"demo": _demo()})) as get:
        demo = sync.fetch()
    assert demo["company"] == "ACME"
    assert get.call_args.args[0] == f"{BASE}/api/demo/mia"
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer jwt-demo"


def test_un_usuario_sin_demo_no_entra_en_modo_demo(sync):
    with patch("requests.get", return_value=_response(200, {"demo": None})):
        assert sync.fetch() is None
    with patch("requests.get", return_value=_response(404)):
        assert sync.fetch() is None


def test_plan_empareja_subcarpetas_y_detecta_nuevos_y_huerfanos(sync, tmp_path):
    base = tmp_path / "demo"
    sync.ensure_folders(str(base), _demo())
    _write(base / "Contratos" / "Sub" / "informe.pdf")  # ya está en InfoHub
    _write(base / "Expedientes" / "caso-1.docx")  # nuevo
    _write(base / "Expedientes" / "~$caso-1.docx")  # temporal de Word

    plan = sync.plan(str(base), _demo())
    assert plan["Contratos"]["a_subir"] == []
    assert plan["Contratos"]["huerfanos"] == []
    assert [(rel, remote) for _, rel, remote in plan["Expedientes"]["a_subir"]] == [
        ("caso-1.docx", "caso-1.docx")
    ]

    (base / "Contratos" / "Sub" / "informe.pdf").unlink()
    plan = sync.plan(str(base), _demo())
    assert plan["Contratos"]["huerfanos"] == [{"docId": "d-1", "nombre": "Sub__informe.pdf", "bytes": 1000}]


def test_plan_separa_lo_que_no_entra_en_el_cupo_compartido(sync, tmp_path):
    base = tmp_path / "demo"
    sync.ensure_folders(str(base), _demo())
    _write(base / "Contratos" / "Sub" / "informe.pdf")
    _write(base / "Contratos" / "a.txt", b"a" * 10)
    _write(base / "Expedientes" / "b.txt", b"b" * 10)

    # Queda un solo documento libre en toda la demo.
    plan = sync.plan(str(base), _demo(maxDocs=2))
    assert [rel for _, rel, _ in plan["Contratos"]["a_subir"]] == ["a.txt"]
    assert plan["Expedientes"]["a_subir"] == []
    assert plan["Expedientes"]["sin_cupo"] == ["b.txt"]

    # Sin espacio para 10 bytes más.
    plan = sync.plan(str(base), _demo(maxBytes=1005))
    assert plan["Contratos"]["sin_cupo"] == ["a.txt"]


def test_sincronizar_quita_antes_de_subir_y_usa_solo_la_sesion(sync, tmp_path):
    base = tmp_path / "demo"
    sync.ensure_folders(str(base), _demo())
    _write(base / "Expedientes" / "caso.pdf", b"%PDF")  # informe.pdf ya no está: se quita

    order = []

    def delete(url, **kwargs):
        order.append("delete")
        assert url == f"{BASE}/api/demo/documentos/d-1"
        assert kwargs["headers"]["Authorization"] == "Bearer jwt-demo"
        return _response(200, {"success": True})

    def post(url, **kwargs):
        order.append("post")
        assert url == f"{BASE}/api/workspace/expedientes/upload-and-embed"
        assert kwargs["headers"]["Authorization"] == "Bearer jwt-demo"
        assert kwargs["files"]["file"][0] == "caso.pdf"
        return _response(200, {"success": True})

    with patch("requests.get", return_value=_response(200, {"demo": _demo()})), \
            patch("requests.delete", side_effect=delete), \
            patch("requests.post", side_effect=post):
        result = sync.sync(str(base))

    assert order == ["delete", "post"]
    assert result["status"] == "success"
    assert (result["uploaded"], result["deleted"]) == (1, 1)


def test_un_413_se_informa_sin_cortar_el_resto(sync, tmp_path):
    base = tmp_path / "demo"
    sync.ensure_folders(str(base), _demo())
    _write(base / "Contratos" / "Sub" / "informe.pdf")
    _write(base / "Expedientes" / "a.pdf")
    _write(base / "Expedientes" / "b.pdf")

    responses = [
        _response(413, {"success": False, "error": "Se alcanzó el límite de la demo."}),
        _response(200, {"success": True}),
    ]
    with patch("requests.get", return_value=_response(200, {"demo": _demo()})), \
            patch("requests.post", side_effect=responses) as post:
        result = sync.sync(str(base))

    assert post.call_count == 2
    assert result["status"] == "warning"
    assert result["uploaded"] == 1
    assert "a.pdf: Se alcanzó el límite de la demo." in result["errors"]


def test_simular_no_cambia_nada(sync, tmp_path):
    base = tmp_path / "demo"
    sync.ensure_folders(str(base), _demo())
    _write(base / "Expedientes" / "a.pdf")
    with patch("requests.get", return_value=_response(200, {"demo": _demo()})), \
            patch("requests.post") as post, patch("requests.delete") as delete:
        result = sync.simulate(str(base))
    post.assert_not_called()
    delete.assert_not_called()
    assert result["simulation"]["Expedientes"]["a_subir"] == ["a.pdf"]
    assert result["simulation"]["Contratos"]["huerfanos"] == ["Sub__informe.pdf"]


def test_sin_carpeta_elegida_no_sincroniza(sync):
    with patch("requests.get", return_value=_response(200, {"demo": _demo()})):
        assert sync.sync("")["status"] == "error"
