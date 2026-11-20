"""Resolver de slugs: un alias no debe ocultar el workspace si su destino no existe."""

from unittest.mock import MagicMock, patch

import workspace_map


def _resp(workspaces):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"workspaces": workspaces}
    return resp


def test_alias_cuyo_destino_no_existe_cae_al_nombre_de_la_carpeta():
    # Instalación donde el workspace se llama 'odoo' y no 'odoo17'.
    with patch("workspace_map.requests.get", return_value=_resp([{"name": "odoo", "slug": "odoo"}])):
        resolver = workspace_map.WorkspaceResolver("http://infohub:3001", "key")
        assert resolver.slug("odoo") == ("odoo", True)


def test_alias_existente_sigue_mandando():
    with patch(
        "workspace_map.requests.get",
        return_value=_resp([{"name": "odoo 17", "slug": "odoo17"}]),
    ):
        resolver = workspace_map.WorkspaceResolver("http://infohub:3001", "key")
        assert resolver.slug("odoo") == ("odoo17", True)


def test_sin_coincidencia_devuelve_la_regla_antigua():
    with patch("workspace_map.requests.get", return_value=_resp([])):
        resolver = workspace_map.WorkspaceResolver("http://infohub:3001", "key")
        assert resolver.slug("Zoho Tickets") == ("zoho-tickets", False)
