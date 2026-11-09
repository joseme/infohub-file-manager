"""Fixtures comunes a toda la suite."""

import pytest

import sync_guards


@pytest.fixture(autouse=True)
def _estado_fuentes_aislado(tmp_path, monkeypatch):
    """Ningún test lee el logs/estado_fuentes.json real del proyecto."""
    monkeypatch.setattr(sync_guards, "ESTADO_FUENTES", tmp_path / "estado_fuentes_inexistente.json")
