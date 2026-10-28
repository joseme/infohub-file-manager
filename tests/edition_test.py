"""Ediciones Business / Enterprise: la edición sale de InfoHub y ee/ es opcional."""

import os
from unittest.mock import MagicMock, patch

import edition


def _response(status=200, body=None):
    resp = MagicMock(status_code=status)
    resp.json.return_value = body or {}
    return resp


def test_lee_la_edicion_de_infohub():
    with patch("edition.requests.get", return_value=_response(body={"settings": {"Edition": "enterprise"}})) as get:
        assert edition.fetch_edition("http://infohub:3001/", "key") == "enterprise"
    url = get.call_args.args[0]
    assert url == "http://infohub:3001/api/v1/system"
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer key"


def test_errores_o_infohub_sin_el_campo_son_business():
    cases = [
        _response(status=403),
        _response(body={"settings": {}}),  # InfoHub anterior al paso 6
        _response(body={"settings": {"Edition": "premium"}}),
    ]
    for resp in cases:
        with patch("edition.requests.get", return_value=resp):
            assert edition.fetch_edition("http://infohub", "key") == "business"
    with patch("edition.requests.get", side_effect=OSError("sin red")):
        assert edition.fetch_edition("http://infohub", "key") == "business"


def test_enterprise_requiere_infohub_enterprise_y_el_paquete_ee():
    assert edition.is_enterprise("enterprise", ee_module=object())
    assert not edition.is_enterprise("business", ee_module=object())
    assert not edition.is_enterprise("enterprise", ee_module=None)  # imagen Business


def test_el_paquete_ee_segun_la_edicion_de_la_ci():
    """En la CI, business corre sin ee/ (como la imagen); si no, ee/ está y se registra."""
    if os.getenv("INFOHUB_EDITION") == "business":
        assert edition.ee is None
        return
    assert edition.ee is not None
    edition.ee.register(page=MagicMock(), manager=MagicMock())


def test_el_codigo_comun_no_importa_ee_directamente():
    """La imagen Business no trae ee/: solo edition.py puede importarlo."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    offenders = []
    for name in os.listdir(root):
        if name.endswith(".py") and name != "edition.py":
            with open(os.path.join(root, name), encoding="utf-8") as f:
                source = f.read()
            if "import ee" in source or "from ee" in source:
                offenders.append(name)
    assert offenders == []
