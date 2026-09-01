"""Trwałe ustawienia selekty (~/.selekta/config.json).

Trzyma to, co ma przeżyć restart apki: adres i klucz API slskd, ścieżkę
biblioteki, katalog eksportu. Zmienne środowiskowe (SELEKTA_SLSKD_URL,
SELEKTA_SLSKD_API_KEY) mają pierwszeństwo — dzięki temu uruchomienie z
własnym kluczem nadal działa i nic nie nadpisuje pliku.

Plik dostaje prawa 0600: klucz API daje pełny dostęp do slskd, więc nie
ma powodu, by czytali go inni użytkownicy maszyny.
"""
from __future__ import annotations

import json
import os
from typing import Any

STATE_DIR = os.path.expanduser("~/.selekta")
CONFIG_PATH = os.path.join(STATE_DIR, "config.json")

DEFAULTS: dict[str, Any] = {
    "slskd_url": "http://localhost:5030",
    "slskd_api_key": "",
    "library_folder": "",
    "slskd_binary": "",
    "downloads_root": "~/Music/selekta",
}

# klucze, których wartości nigdy nie pokazujemy w całości w UI/logach
SECRET_KEYS = ("slskd_api_key",)


def load() -> dict[str, Any]:
    """Ustawienia z pliku, uzupełnione domyślnymi."""
    data = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as fh:
            stored = json.load(fh)
        if isinstance(stored, dict):
            data.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return data


def save(values: dict[str, Any]) -> dict[str, Any]:
    """Zapisz podzbiór ustawień (zapis atomowy, prawa 0600)."""
    data = load()
    data.update({k: v for k, v in values.items() if k in DEFAULTS})
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG_PATH)
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass
    return data


def get(key: str) -> Any:
    """Wartość ustawienia; zmienna środowiskowa wygrywa z plikiem."""
    env = os.environ.get(f"SELEKTA_{key.upper()}")
    if env:
        return env
    return load().get(key, DEFAULTS.get(key))


def masked(values: dict[str, Any] | None = None) -> dict[str, Any]:
    """Ustawienia bezpieczne do pokazania: sekrety jako ●●● + ogon."""
    data = dict(values or load())
    for k in SECRET_KEYS:
        v = str(data.get(k) or "")
        data[k] = f"●●●●{v[-4:]}" if len(v) > 8 else ("" if not v else "●●●●")
        data[f"{k}_set"] = bool(v)
    return data
