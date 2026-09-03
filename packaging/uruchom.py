"""Skrypt startowy pakietu .app.

PyInstaller uruchamia plik wejściowy jako luźny skrypt, nie jako moduł
pakietu — stąd ``from . import web`` w selekta/app.py padało z „attempted
relative import with no known parent package". Ten plik importuje pakiet
absolutnie i oddaje sterowanie.
"""
from selekta.app import main

if __name__ == "__main__":
    main()
