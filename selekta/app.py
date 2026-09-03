"""Punkt wejścia wersji do pobrania (Selekta.app).

Człowiek klika ikonę — i ma dostać dashboard w przeglądarce, bez terminala,
bez ``--folder``, bez Homebrew. Ten moduł robi dokładnie to, co robi
``selekta serve``, tylko sam dobiera brakujące rzeczy:

* folder biblioteki bierze z ustawień; gdy go jeszcze nie ma, startuje na
  ``~/Music`` i pokazuje kreator, w którym użytkownik wskazuje właściwy;
* port wybiera wolny, żeby druga instancja albo cudzy serwer na 8756 nie
  wywaliły apki z komunikatem, którego laik nie zrozumie;
* od razu pokazuje ekran powitalny (logo) w przeglądarce — lokalny plik,
  więc nie czeka na serwer — a ten sam ekran sam przełącza się na
  dashboard w chwili, gdy serwer zacznie odpowiadać;
* ffmpeg bierze z pakietu (patrz ``narzedzia``), więc analiza działa od razu.

Zamknięcie: Cmd+Q na ikonie w Docku kończy proces, a razem z nim serwer,
obserwator i kolejkę pobierania (jej stan jest zapisany na dysku i wznowi
się przy następnym uruchomieniu).
"""
from __future__ import annotations

import base64
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser

PORT_DOMYSLNY = 8756


def _logo_b64() -> str:
    """Logo z pakietu (albo z repo przy uruchomieniu ze źródeł)."""
    kandydaci = [
        os.path.join(getattr(sys, "_MEIPASS", ""), "packaging", "logo.png"),
        os.path.join(os.path.dirname(sys.executable), "..", "Resources", "packaging", "logo.png"),
        os.path.join(os.path.dirname(__file__), "..", "packaging", "logo.png"),
    ]
    for k in kandydaci:
        if k and os.path.isfile(k):
            with open(k, "rb") as fh:
                return base64.b64encode(fh.read()).decode("ascii")
    return ""


def splash_html(url: str) -> str:
    """Ekran powitalny: logo na jasnym tle, sam przechodzi do dashboardu.

    Jasne tło celowo, choć dashboard jest ciemny: logo ma czarny napis
    „made by Voyage", który na ciemnym tle znika.

    Plik lokalny (file://), więc otwiera się natychmiast po kliknięciu ikony,
    zanim serwer wstanie. Skrypt puka co 300 ms w /api/status; fetch w trybie
    no-cors rozstrzyga „odpowiada / nie odpowiada" bez nagłówków CORS.
    """
    logo = _logo_b64()
    obraz = (f'<img src="data:image/png;base64,{logo}" alt="Selekta DJ">'
             if logo else '<div class="t">SELEKTA</div>')
    return f"""<!doctype html><html lang="pl"><head><meta charset="utf-8">
<title>Selekta</title><style>
html,body{{height:100%;margin:0;background:#f4f5f7;color:#5a646e;font-family:-apple-system,system-ui,sans-serif}}
body{{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:28px}}
img{{width:min(62vw,560px);opacity:0;animation:in 1.1s ease-out forwards}}
.t{{font-size:64px;font-weight:800;color:#1b2128;letter-spacing:.08em}}
.s{{font-size:14px;letter-spacing:.14em;text-transform:uppercase;opacity:.75}}
.k{{width:220px;height:3px;background:#dfe3e8;border-radius:2px;overflow:hidden}}
.k i{{display:block;width:40%;height:100%;background:#ff7a1a;animation:go 1.2s ease-in-out infinite}}
@keyframes in{{from{{opacity:0;transform:scale(.96)}}to{{opacity:1;transform:none}}}}
@keyframes go{{0%{{transform:translateX(-100%)}}100%{{transform:translateX(250%)}}}}
@media (prefers-reduced-motion: reduce){{img,.k i{{animation:none;opacity:1}}}}
</style></head><body>
{obraz}
<div class="s" id="s">uruchamiam</div><div class="k"><i></i></div>
<script>
const url = {url!r};
let proby = 0;
async function puk(){{
  try {{ await fetch(url + "/api/status", {{mode: "no-cors", cache: "no-store"}}); location.replace(url); return; }}
  catch (e) {{ proby++; if (proby > 200) document.getElementById("s").textContent = "serwer nie odpowiada — zamknij i uruchom ponownie"; }}
  setTimeout(puk, 300);
}}
setTimeout(puk, 400);
</script></body></html>"""


def _otworz_splash(url: str) -> None:
    katalog = os.path.join(tempfile.gettempdir(), "selekta")
    os.makedirs(katalog, exist_ok=True)
    plik = os.path.join(katalog, "start.html")
    with open(plik, "w", encoding="utf-8") as fh:
        fh.write(splash_html(url))
    webbrowser.open("file://" + plik)


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
    if os.environ.get("SELEKTA_BEZ_PRZEGLADARKI"):
        pass                                   # testy dymne i CI
    elif os.environ.get("SELEKTA_BEZ_SPLASH"):
        threading.Thread(target=_otworz_gdy_odpowie, args=(url,), daemon=True).start()
    else:
        _otworz_splash(url)
    from . import web
    try:
        web.serve(_folder_biblioteki(), port=port)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
