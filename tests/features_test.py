"""Funciones opcionales: la lista sale de InfoHub (settings.Features)."""

from unittest.mock import MagicMock, patch

import features


def _response(status=200, body=None):
    resp = MagicMock(status_code=status)
    resp.json.return_value = body or {}
    return resp


def test_lee_las_funciones_de_infohub():
    body = {"settings": {"Features": ["auditoria", "sso"]}}
    with patch("features.requests.get", return_value=_response(body=body)) as get:
        assert features.fetch_features("http://infohub:3001/", "key") == ["auditoria", "sso"]
    assert get.call_args.args[0] == "http://infohub:3001/api/v1/system"
    assert get.call_args.kwargs["headers"]["Authorization"] == "Bearer key"


def test_errores_o_infohub_sin_el_campo_no_activan_nada():
    cases = [
        _response(status=403),
        _response(body={"settings": {}}),  # InfoHub sin licencias
        _response(body={"settings": {"Features": "auditoria"}}),
    ]
    for resp in cases:
        with patch("features.requests.get", return_value=resp):
            assert features.fetch_features("http://infohub", "key") == []
    with patch("features.requests.get", side_effect=OSError("sin red")):
        assert features.fetch_features("http://infohub", "key") == []


def test_descarta_valores_que_no_son_ids():
    body = {"settings": {"Features": ["auditoria", 3, None]}}
    with patch("features.requests.get", return_value=_response(body=body)):
        assert features.fetch_features("http://infohub", "key") == ["auditoria"]


def test_is_enabled():
    assert features.is_enabled(["auditoria"], "auditoria")
    assert not features.is_enabled(["auditoria"], "sso")
    assert not features.is_enabled([], "auditoria")
