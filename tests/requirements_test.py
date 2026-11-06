"""Guards de version: flet y flet-web deben coincidir y FastAPI no romper flet-web."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _pins(path: Path) -> dict[str, str]:
    pins = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.split("#", 1)[0].strip()
        if "==" in line:
            name, version = line.split("==", 1)
            pins[name.strip().lower()] = version.strip()
    return pins


def test_flet_y_flet_web_comparten_version():
    pins = _pins(ROOT / "requirements.txt")
    assert pins["flet"] == pins["flet-web"]


def test_fastapi_no_alcanza_la_version_que_rompe_flet_web():
    version = _pins(ROOT / "requirements.txt")["fastapi"]
    assert tuple(map(int, version.split("."))) < (0, 156)


def test_pins_solo_viven_en_requirements():
    # Si un script o el Dockerfile repite pins, pueden quedar desincronizados.
    for name in ("Dockerfile", "build_linux.sh", "build_windows.bat"):
        text = (ROOT / name).read_text(encoding="utf-8", errors="replace")
        assert not re.search(r"(flet-web|fastapi)==", text), name
