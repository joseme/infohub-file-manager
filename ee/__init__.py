"""Funciones exclusivas de InfoHub File Manager Enterprise.

app.py llama a register() solo si InfoHub es Enterprise (edition.py). La imagen
Business se construye sin este paquete: el código común nunca lo importa
directamente, siempre a través de edition.py.
"""


def register(page, manager) -> None:
    """Agrega a la interfaz lo de Enterprise. Por ahora no hay funciones."""
