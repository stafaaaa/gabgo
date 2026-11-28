"""Dauerhafte Einstellungen (Ordner, Ziel-Datei, KI-Anbieter, Modell, API-Key).

Ablage: %APPDATA%\\Tankbelege\\einstellungen.json (Windows) bzw. ~/.config/tankbelege/.
API-Keys sind unter Windows per DPAPI an das Benutzerkonto gebunden verschlüsselt.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path


def pfad() -> Path:
    if os.environ.get("TANKBELEGE_EINSTELLUNGEN"):
        return Path(os.environ["TANKBELEGE_EINSTELLUNGEN"])
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "Tankbelege" / "einstellungen.json"
    return Path.home() / ".config" / "tankbelege" / "einstellungen.json"


def laden() -> dict:
    try:
        daten = json.loads(pfad().read_text(encoding="utf-8"))
        return daten if isinstance(daten, dict) else {}
    except (OSError, ValueError):
        return {}


def speichern(daten: dict):
    p = pfad()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(daten, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    if os.name != "nt":
        os.chmod(p, 0o600)


def _dpapi(data: bytes, schuetzen: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    puffer = ctypes.create_string_buffer(data, len(data))
    ein = Blob(len(data), ctypes.cast(puffer, ctypes.POINTER(ctypes.c_char)))
    aus = Blob()
    crypt32 = ctypes.windll.crypt32
    funktion = crypt32.CryptProtectData if schuetzen else crypt32.CryptUnprotectData
    if not funktion(ctypes.byref(ein), None, None, None, None, 0x01, ctypes.byref(aus)):
        raise OSError("DPAPI fehlgeschlagen")
    try:
        return ctypes.string_at(aus.pbData, aus.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(aus.pbData)


def verschluesseln(text: str) -> str:
    if not text:
        return ""
    if os.name == "nt":
        return "dpapi:" + base64.b64encode(_dpapi(text.encode("utf-8"), True)).decode("ascii")
    return "klar:" + base64.b64encode(text.encode("utf-8")).decode("ascii")


def entschluesseln(wert: str) -> str:
    try:
        art, _, daten = (wert or "").partition(":")
        roh = base64.b64decode(daten)
        if art == "dpapi":
            return _dpapi(roh, False).decode("utf-8")
        if art == "klar":
            return roh.decode("utf-8")
    except (OSError, ValueError):
        pass
    return ""
