"""KI-Fallback für unklare Belege: Ollama (lokal), OpenRouter, OpenAI, Gemini oder Anthropic.

Bei Vision-Modellen geht das Seitenbild direkt an die KI, der OCR-Text nur als Hilfe.
"""
from __future__ import annotations

import base64
import io
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

import belege_core as bc

# Schlüssel: (Anzeige, Standardmodell, API-Key nötig)
ANBIETER = {
    "aus": ("Aus (nur OCR)", "", False),
    "ollama": ("Ollama (lokal)", bc.OLLAMA_MODEL, False),
    "openrouter": ("OpenRouter (Cloud)", "anthropic/claude-haiku-5.5", True),
    "openai": ("OpenAI (direkt)", "gpt-5.4-mini", True),
    "gemini": ("Gemini (direkt)", "gemini-3.8-flash", True),
    "anthropic": ("Anthropic (direkt)", "claude-haiku-5-5", True),
}
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


@dataclass
class KiEinstellung:
    anbieter: str = "aus"
    modell: str = ""
    api_key: str = ""
    bild: bool = True
    url: str = bc.OLLAMA_URL

    @classmethod
    def aus_wert(cls, wert) -> "KiEinstellung":
        if isinstance(wert, cls):
            return wert
        return cls("ollama", bc.OLLAMA_MODEL, bild=False) if wert else cls()

    @property
    def aktiv(self) -> bool:
        return self.anbieter in ANBIETER and self.anbieter != "aus"

    @property
    def modell_oder_standard(self) -> str:
        return self.modell.strip() or ANBIETER.get(self.anbieter, ("", "", False))[1]

    def beschreibung(self) -> str:
        name = ANBIETER.get(self.anbieter, (self.anbieter,))[0]
        return name if not self.aktiv else f"{name}, {self.modell_oder_standard}"


def _bild_b64(img) -> str:
    from PIL import Image
    img = img.convert("RGB")
    img.thumbnail((1600, 1600), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _post(url: str, body: dict, headers: dict, timeout: int) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            detail = ""
        raise ValueError(f"HTTP {exc.code} {exc.reason} {detail}".strip()) from exc


def json_aus_text(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, ende = text.find("{"), text.rfind("}")
    if start < 0 or ende < start:
        raise ValueError(f"keine JSON-Antwort: {text[:120]!r}")
    return json.loads(text[start:ende + 1])


def _antwort_text(ki: KiEinstellung, prompt: str, b64: str | None, timeout: int) -> str:
    modell = ki.modell_oder_standard
    if ki.anbieter == "ollama":
        body = {"model": modell, "prompt": prompt, "stream": False, "format": "json", "options": {"temperature": 0}}
        if b64:
            body["images"] = [b64]
        return _post(ki.url, body, {}, timeout).get("response") or "{}"
    if not ki.api_key.strip():
        raise ValueError("kein API-Key eingetragen")
    key = ki.api_key.strip()
    if ki.anbieter in ("openrouter", "openai"):
        inhalt = [{"type": "text", "text": prompt}]
        if b64:
            inhalt.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        headers = {"Authorization": f"Bearer {key}"}
        if ki.anbieter == "openrouter":
            headers["X-Title"] = "Tankbelege"
        url = OPENROUTER_URL if ki.anbieter == "openrouter" else OPENAI_URL
        data = _post(url, {"model": modell, "messages": [{"role": "user", "content": inhalt}]}, headers, timeout)
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
        return content or ""
    if ki.anbieter == "gemini":
        teile = [{"text": prompt}]
        if b64:
            teile.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})
        body = {"contents": [{"role": "user", "parts": teile}],
                "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}
        data = _post(GEMINI_URL.format(model=modell), body, {"x-goog-api-key": key}, timeout)
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
    if ki.anbieter == "anthropic":
        inhalt = []
        if b64:
            inhalt.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})
        inhalt.append({"type": "text", "text": prompt})
        body = {"model": modell, "max_tokens": 1024, "messages": [{"role": "user", "content": inhalt}]}
        data = _post(ANTHROPIC_URL, body, {"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout)
        return "".join(c.get("text", "") for c in data["content"] if c.get("type") == "text")
    raise ValueError(f"unbekannter KI-Anbieter {ki.anbieter!r}")


def frage_ki(ki: KiEinstellung, text: str | None, bild, fahrzeuge: bc.FahrzeugListe,
             timeout: int = 180) -> bc.BelegDaten:
    b64 = _bild_b64(bild) if bild is not None else None
    prompt = bc.ki_prompt(text, fahrzeuge, b64 is not None)
    return bc._from_llm(json_aus_text(_antwort_text(ki, prompt, b64, timeout)), fahrzeuge)
