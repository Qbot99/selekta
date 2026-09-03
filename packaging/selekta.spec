# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller: Selekta.app dla macOS.

Budowane przez packaging/build_mac.sh (lokalnie) i .github/workflows/release.yml
(na tag). Zasady:

* ffmpeg i ffprobe jadą W ŚRODKU pakietu razem z bibliotekami dynamicznymi —
  PyInstaller sam dociąga zależności binarek wskazanych w ``binaries``;
  kod znajduje je przez selekta.narzedzia (katalog obok binarki apki);
* dashboard (static/index.html) jako dane pakietu;
* uvicorn/fastapi importują sporo dynamicznie — stąd hiddenimports.

Architektura = architektura runnera (arm64 na macos-14, x86_64 na macos-13).
"""
import os
import shutil
import sys

from PyInstaller.utils.hooks import collect_submodules

KORZEN = os.path.abspath(os.path.join(SPECPATH, ".."))
sys.path.insert(0, KORZEN)

def _bin(nazwa: str) -> str:
    p = os.environ.get(f"SELEKTA_{nazwa.upper()}") or shutil.which(nazwa)
    if not p:
        raise SystemExit(f"brak {nazwa} — zainstaluj (brew install ffmpeg) "
                         f"albo wskaż przez SELEKTA_{nazwa.upper()}")
    return os.path.realpath(p)

binaries = [(_bin("ffmpeg"), "."), (_bin("ffprobe"), ".")]
datas = [(os.path.join(KORZEN, "selekta", "static"), "selekta/static")]

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("fastapi")
    + collect_submodules("starlette")
    + collect_submodules("anyio")
    + ["multipart", "python_multipart", "email.mime.multipart"]
)

a = Analysis(
    [os.path.join(SPECPATH, "uruchom.py")],
    pathex=[KORZEN],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "pandas", "PIL", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Selekta",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    target_arch=None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Selekta")

app = BUNDLE(
    coll,
    name="Selekta.app",
    icon=os.path.join(SPECPATH, "Selekta.icns") if os.path.exists(os.path.join(SPECPATH, "Selekta.icns")) else None,
    bundle_identifier="pl.selekta.app",
    info_plist={
        "CFBundleName": "Selekta",
        "CFBundleDisplayName": "Selekta",
        "CFBundleShortVersionString": os.environ.get("SELEKTA_VERSION", "0.0.0"),
        "NSHighResolutionCapable": True,
        # apka otwiera przeglądarkę i sama nie ma okna — bez tego macOS
        # pokazuje ją w Docku jak zawieszoną
        "LSUIElement": False,
        "NSHumanReadableCopyright": "MIT — github.com/Qbot99/selekta",
    },
)
