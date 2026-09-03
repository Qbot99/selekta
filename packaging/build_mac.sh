#!/usr/bin/env bash
# Zbuduj Selekta.app lokalnie (to samo, co robi CI przy wydaniu).
#
#   packaging/build_mac.sh            -> dist/Selekta.app + dist/Selekta-<wersja>-<arch>.zip
#
# Wymaga: python3 >= 3.11, ffmpeg w PATH (brew install ffmpeg).
set -euo pipefail
cd "$(dirname "$0")/.."

WERSJA="${SELEKTA_VERSION:-$(python3 -c 'import re;print(re.search(r"__version__ = \"([^\"]+)\"", open("selekta/__init__.py").read()).group(1))')}"
ARCH="$(uname -m)"
export SELEKTA_VERSION="$WERSJA"

if [ ! -d .build-venv ]; then python3 -m venv .build-venv; fi
# shellcheck disable=SC1091
source .build-venv/bin/activate
pip install -q --upgrade pip
pip install -q ".[web,macos]" pyinstaller

rm -rf build dist
pyinstaller --noconfirm --clean packaging/selekta.spec

# test dymny: binarka startuje i odpowiada na /api/status — inaczej budowanie
# ma PAŚĆ, nie zostawić zip z apką, która wywala się po kliknięciu
SELEKTA_PORT=8799 SELEKTA_BEZ_PRZEGLADARKI=1 dist/Selekta.app/Contents/MacOS/Selekta &
PID=$!
OK=0
for _ in $(seq 1 40); do
  if curl -fs http://127.0.0.1:8799/api/status >/dev/null 2>&1; then OK=1; break; fi
  sleep 0.5
done
kill $PID 2>/dev/null || true
if [ "$OK" != 1 ]; then echo "test dymny NIE PRZESZEDŁ — apka nie odpowiada"; exit 1; fi
echo "test dymny OK"

( cd dist && ditto -c -k --keepParent Selekta.app "Selekta-${WERSJA}-${ARCH}.zip" )
echo "gotowe: dist/Selekta-${WERSJA}-${ARCH}.zip"
