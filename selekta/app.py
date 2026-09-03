"""Punkt wejścia wersji do pobrania (Selekta.app).

Człowiek klika ikonę — i ma dostać dashboard w przeglądarce, bez terminala,
bez ``--folder``, bez Homebrew. Ten moduł robi dokładnie to, co robi
``selekta serve``, tylko sam dobiera brakujące rzeczy:

* folder biblioteki bierze z ustawień; gdy go jeszcze nie ma, startuje na
  ``~/Music`` i pokazuje kreator, w którym użytkownik wskazuje właściwy;
* port wybiera wolny, żeby druga instancja albo cudzy serwer na 8756 nie
  wywaliły apki z komunikatem, którego laik nie zrozumie;
* otwiera przeglądarkę dopiero wtedy, gdy serwer naprawdę odpowiada;
* ffmpeg bierze z pakietu (patrz ``narzedzia``), więc analiza działa od razu.

Zamknięcie: Cmd+Q na ikonie w Docku kończy proces, a razem z nim serwer,
obserwator i kolejkę pobierania (jej stan jest zapisany na dysku i wznowi
się przy następnym uruchomieniu).
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

PORT_DOMYSLNY = 8756


def _wolny_port(preferowany: int = PORT_DOMYSLNY) -> int:
    for port in (preferowany, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    return preferowany


def _folder_biblioteki() -> str:
    from . import config
    zapisany = config.get("library_folder")
    if zapisany and os.path.isdir(os.path.expanduser(zapisany)):
        return os.path.expanduser(zapisany)
    for kandydat in ("~/Music", "~/Muzyka", "~"):
        p = os.path.expanduser(kandydat)
        if os.path.isdir(p):
            return p
    return os.path.expanduser("~")


def _otworz_gdy_odpowie(url: str, limit_s: float = 20.0) -> None:
    start = time.time()
    while time.time() - start < limit_s:
        try:
            with urllib.request.urlopen(url + "/api/status", timeout=1):
                break
        except Exception:  # noqa: BLE001 — serwer jeszcze wstaje
            time.sleep(0.25)
    webbrowser.open(url)


def main() -> None:
    port = int(os.environ.get("SELEKTA_PORT") or _wolny_port())
    url = f"http://127.0.0.1:{port}"
    threading.Thread(target=_otworz_gdy_odpowie, args=(url,), daemon=True).start()
    from . import web
    try:
        web.serve(_folder_biblioteki(), port=port)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
