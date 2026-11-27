"""Texterkennung und Auswertung gescannter Tankbelege."""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pymupdf
from PIL import Image, ImageFilter, ImageOps

TESSERACT_WINDOWS = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2:latest"
BELEG_ENDUNGEN = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
MIN_TEXTLAYER_ZEICHEN = 40

AMOUNT = r"(?<![\d.,])(\d{1,3}(?:\.\d{3})+,\d{2}|\d+[.,]\d{2})(?![\d])"
FUEL_WORDS = re.compile(
    r"super|diesel|benzin|e\s?10\b|\be\s?5\b|euro\s?95|v-?power|ultimate|excellium|"
    r"premium|kraftstoff|autogas|\blpg\b|\bcng\b|erdgas|\bhvo\b|bleifrei",
    re.I,
)
ADBLUE = re.compile(r"ad\s?blue|\bdef\b|harnstoff", re.I)
WASH_WORDS = re.compile(r"w[äa]e?sche|wasch|\bwash|glanz|autopflege|pflegeprogramm", re.I)
TOTAL_WORDS = re.compile(r"\bsumme\b|gesamt|zu zahlen|\bbetrag\b|\btotal\b", re.I)
KM_WORDS = re.compile(r"kilometer\s*-?\s*stand|km\s*[-.]?\s*stand|kilometer|\bkm\s*[:=]", re.I)
PLATE_WORDS = re.compile(r"kennz|kfz|fahrzeug|\bkz\b", re.I)
PLATE_ANYWHERE = re.compile(
    r"\b[GC6][EF€]\s*[-.\s]\s*[EL][LEI1|]\s*[-.\s]?\s*([0-9OoIlSBZ|]{1,4}\s?[A-Z€£0-9]?)\b"
)
UNIT_PRICE = re.compile(
    r"(\d[.,]\d{3})\s*(?:€|EUR|E|e|«|&|£)?\s*/\s*(?:l\b|liter|ltr|kg)", re.I
)
QTY = re.compile(r"(?<![\d.,])(\d{1,3}[.,]\d{2,3})\s*(liter|ltr|l|kg)\b", re.I)
DATE = re.compile(r"(?<!\d)(\d{1,2})\s?[./-]\s?(\d{1,2})\s?[./-]\s?(\d{4}|\d{2})(?!\d)")

DIGIT_MAP = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "I": "1", "l": "1", "|": "1",
                           "!": "1", "S": "5", "s": "5", "$": "5", "B": "8", "Z": "2", "z": "2",
                           "G": "6", "b": "6", "T": "7", "A": "4"})
E_LIKE = set("EeF€£6B83CGc")


def to_float(text: str) -> float:
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    return float(text)


def amounts(line: str) -> list[float]:
    return [to_float(m.group(1)) for m in re.finditer(AMOUNT, line)
            if not re.match(r"\s*(?:€|EUR|E)?\s*/", line[m.end():])]


@dataclass
class Fahrzeug:
    endziffer: object
    kennzeichen: str
    fahrer: str


class FahrzeugListe:
    def __init__(self, fahrzeuge: list[Fahrzeug]):
        self.fahrzeuge = fahrzeuge
        self.keys: dict[str, Fahrzeug] = {}
        for f in fahrzeuge:
            self.keys.setdefault(self._norm(f.endziffer), f)
        for f in fahrzeuge:
            tail = str(f.kennzeichen or "").split()
            if tail:
                self.keys.setdefault(self._norm(tail[-1]), f)

    @staticmethod
    def _norm(value) -> str:
        return re.sub(r"\s", "", str(value)).upper()

    def _variants(self, token: str) -> list[str]:
        token = token.replace(" ", "")
        if not token:
            return []
        digits = token.translate(DIGIT_MAP).upper()
        with_e = digits[:-1] + "E" if token[-1] in E_LIKE else None
        if token[-1].isalpha() or token[-1] in "€£":
            order = [with_e, token.upper(), digits]
        else:
            order = [digits, with_e]
        out = []
        for v in order:
            if v and v not in out:
                out.append(v)
        return out

    def match_token(self, token: str, fuzzy: bool = True):
        """Liefert (Fahrzeug, Hinweis) oder (None, None)."""
        variants = self._variants(token)
        for v in variants:
            if v in self.keys:
                note = None if v == token.upper() else f"OCR-Korrektur '{token}' -> '{self.keys[v].endziffer}'"
                return self.keys[v], note
        if not fuzzy:
            return None, None
        best, best_d, tie = None, 99, False
        for v in variants:
            if len(v) < 3:
                continue
            for k, f in self.keys.items():
                d = _levenshtein(v, k)
                if d < best_d:
                    best, best_d, tie = f, d, False
                elif d == best_d and f is not best:
                    tie = True
        if best is not None and best_d == 1 and not tie:
            return best, f"unsichere Zuordnung '{token}' -> '{best.endziffer}' (ähnlichste Endziffer)"
        return None, None

    def find_in_text(self, text: str):
        """Sucht das Kennzeichen im Belegtext. Liefert (Fahrzeug, Rohwert, Hinweis)."""
        candidates: list[str] = []
        for line in text.splitlines():
            m = PLATE_WORDS.search(line)
            if not m:
                continue
            rest = line[m.end():]
            rest = re.sub(r"^[\w-]*?(zeichen|nummer|nr\.?)\b", "", rest, flags=re.I)
            tokens = re.findall(r"[A-Za-z0-9€£|$!]+", rest)
            while tokens and tokens[0].isalpha() and len(tokens[0]) <= 3 and tokens[0].upper() == tokens[0]:
                tokens.pop(0)
            if tokens:
                if len(tokens) > 1 and len(tokens[1]) == 1 and tokens[1].isalpha():
                    candidates.append(tokens[0] + tokens[1])
                candidates.append(tokens[0])
        candidates += [m.group(1) for m in PLATE_ANYWHERE.finditer(text)]
        for fuzzy in (False, True):
            for cand in candidates:
                fz, note = self.match_token(cand, fuzzy)
                if fz:
                    return fz, cand, note
        return None, (candidates[0] if candidates else None), None


def _levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


@dataclass
class BelegDaten:
    fahrzeug: Fahrzeug | None = None
    kennzeichen_roh: str | None = None
    datum: date | None = None
    menge: float | None = None
    einheit: str | None = None
    kraftstoff_preis: float | None = None
    waesche_preis: float | None = None
    kilometerstand: int | None = None
    summe: float | None = None
    hinweise: list[str] = field(default_factory=list)

    FELDER = ("fahrzeug", "datum", "menge", "einheit", "kraftstoff_preis", "waesche_preis",
              "kilometerstand", "summe")

    @property
    def hat_kraftstoff(self) -> bool:
        return self.menge is not None

    @property
    def hat_waesche(self) -> bool:
        return self.waesche_preis is not None

    def fehlende_pflichtfelder(self) -> list[str]:
        fehlt = []
        if self.fahrzeug is None:
            fehlt.append("Endziffer/Kennzeichen")
        if self.datum is None:
            fehlt.append("Datum")
        if not self.hat_kraftstoff and not self.hat_waesche:
            fehlt.append("Liter/kg bzw. Wäsche")
        if self.hat_kraftstoff and self.kraftstoff_preis is None:
            fehlt.append("Kraftstoffpreis")
        return fehlt


def parse_date(text: str) -> date | None:
    heute = date.today()
    for m in DATE.finditer(text):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        if not (2000 <= y <= heute.year + 1):
            continue
        try:
            return date(y, mo, d)
        except ValueError:
            continue
    return None


def parse_text(text: str, fahrzeuge: FahrzeugListe) -> BelegDaten:
    daten = BelegDaten()
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    daten.fahrzeug, daten.kennzeichen_roh, note = fahrzeuge.find_in_text(text)
    if note:
        daten.hinweise.append(note)
    daten.datum = parse_date(text)

    fuel_lines = []
    for i, line in enumerate(lines):
        if ADBLUE.search(line) or (i and ADBLUE.search(lines[i - 1]) and not FUEL_WORDS.search(line)):
            continue
        fuel_lines.append(line)

    for line in fuel_lines:
        if WASH_WORDS.search(line) or UNIT_PRICE.search(line) and not QTY.search(line):
            continue
        for m in QTY.finditer(line):
            value = to_float(m.group(1))
            if 0.3 <= value <= 1500:
                daten.menge = value
                daten.einheit = "kg" if m.group(2).lower() == "kg" else "l"
                break
        if daten.menge is not None:
            break

    unit_price = None
    m = UNIT_PRICE.search("\n".join(fuel_lines))
    if m:
        unit_price = to_float(m.group(1))

    for i, line in enumerate(lines):
        if WASH_WORDS.search(line) and not QTY.search(line):
            vals = amounts(line)
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if (not vals and nxt and not re.search(r"/\s*st", nxt, re.I) and not TOTAL_WORDS.search(nxt)
                    and not QTY.search(nxt) and not FUEL_WORDS.search(nxt) and not UNIT_PRICE.search(nxt)):
                vals = amounts(nxt)
            if vals:
                daten.waesche_preis = vals[-1]
                break

    for line in lines:
        if TOTAL_WORDS.search(line):
            vals = amounts(line)
            if vals:
                daten.summe = vals[-1]
                break

    if daten.menge is not None:
        all_amounts = [a for l in lines for a in amounts(l)]
        price = None
        if unit_price:
            calc = round(daten.menge * unit_price, 2)
            price = next((a for a in all_amounts if abs(a - calc) <= 0.02), None)
        if price is None:
            for line in lines:
                if FUEL_WORDS.search(line) and not WASH_WORDS.search(line):
                    vals = [v for v in amounts(line) if v != daten.menge]
                    if vals:
                        price = vals[-1]
                        break
        if price is None and daten.summe is not None:
            price = round(daten.summe - (daten.waesche_preis or 0), 2)
            daten.hinweise.append("Kraftstoffpreis aus Summe abgeleitet")
        if price is None and unit_price:
            price = round(daten.menge * unit_price, 2)
            daten.hinweise.append("Kraftstoffpreis aus Liter x Literpreis berechnet")
        daten.kraftstoff_preis = price

    for line in lines:
        m = KM_WORDS.search(line)
        if not m:
            continue
        km = re.search(r"(\d[\d.\s]{0,9}\d)", line[m.end():])
        if km:
            value = int(re.sub(r"\D", "", km.group(1)))
            if 1 <= value <= 3_000_000:
                daten.kilometerstand = value
                break
    return daten


def combine(results: list[BelegDaten]) -> BelegDaten:
    """Mehrheitsentscheid pro Feld über mehrere OCR-Durchläufe."""
    out = BelegDaten()
    for name in BelegDaten.FELDER:
        values = [getattr(r, name) for r in results if getattr(r, name) is not None]
        if not values:
            continue
        keyed = [id(v) if isinstance(v, Fahrzeug) else v for v in values]
        counts = Counter(keyed)
        best_key = max(counts, key=lambda k: (counts[k], -keyed.index(k)))
        setattr(out, name, values[keyed.index(best_key)])
        if len(counts) > 1 and name not in ("einheit",):
            shown = ", ".join(sorted({_fmt(v) for v in values}))
            out.hinweise.append(f"OCR unsicher bei {name}: gelesen {shown} -> {_fmt(getattr(out, name))} gewählt")
    roh = [r.kennzeichen_roh for r in results if r.kennzeichen_roh]
    out.kennzeichen_roh = roh[0] if roh else None
    for r in results:
        if r.fahrzeug is out.fahrzeug:
            for h in r.hinweise:
                if h not in out.hinweise and not h.startswith("Kraftstoffpreis"):
                    out.hinweise.append(h)
            break
    return out


def _fmt(v) -> str:
    if isinstance(v, Fahrzeug):
        return str(v.endziffer)
    if isinstance(v, date):
        return v.strftime("%d.%m.%Y")
    return str(v)


# ---------------------------------------------------------------- OCR

def configure_tesseract() -> str | None:
    import pytesseract
    for cand in (os.environ.get("TESSERACT_CMD"), TESSERACT_WINDOWS, shutil.which("tesseract")):
        if cand and Path(cand).exists():
            pytesseract.pytesseract.tesseract_cmd = cand
            return cand
    return None


def tesseract_lang() -> str:
    import pytesseract
    try:
        langs = set(pytesseract.get_languages(config=""))
    except Exception:
        return "eng"
    return "deu" if "deu" in langs else "eng"


def _gray(img: Image.Image) -> Image.Image:
    return ImageOps.autocontrast(ImageOps.grayscale(img))


def _scale(img: Image.Image, factor: float) -> Image.Image:
    return img.resize((int(img.width * factor), int(img.height * factor)), Image.LANCZOS)


def ocr_varianten(img: Image.Image):
    """Vorverarbeitungen für schwache Thermopapier-Scans und normale Fotos."""
    g = _gray(img)
    if max(g.size) < 1500:
        g = _scale(g, 2)
    yield "kontrast", lambda: g.filter(ImageFilter.MinFilter(3))
    yield "schwelle", lambda: g.point(lambda p: 255 if p > 190 else 0)
    yield "vergroessert", lambda: _scale(g, 2).point(lambda p: 255 if p > 180 else 0)
    yield "original", lambda: g
    yield "vergroessert_weich", lambda: _scale(g, 2)


def _osd_rotation(img: Image.Image) -> int:
    import pytesseract
    try:
        osd = pytesseract.image_to_osd(_gray(img), config="--psm 0")
    except Exception:
        return 0
    angle = int(re.search(r"Rotate: (\d+)", osd).group(1))
    conf = float(re.search(r"Orientation confidence: ([\d.]+)", osd).group(1))
    return angle if conf >= 3 else 0


def ocr_image(img: Image.Image, fahrzeuge: FahrzeugListe, lang: str, max_runs: int = 5):
    import pytesseract
    img = ImageOps.exif_transpose(img).convert("RGB")
    results, texts = [], []
    variants = list(ocr_varianten(img))
    first = pytesseract.image_to_string(variants[0][1](), lang=lang, config="--psm 4")
    first_result = parse_text(first, fahrzeuge)
    if len(first_result.fehlende_pflichtfelder()) >= 3:
        angle = _osd_rotation(img)
        if angle:
            img = img.rotate(-angle, expand=True)
            variants = list(ocr_varianten(img))
            first = pytesseract.image_to_string(variants[0][1](), lang=lang, config="--psm 4")
            first_result = parse_text(first, fahrzeuge)
    texts.append(first)
    results.append(first_result)
    for _, make in variants[1:max_runs]:
        if _consistent(results):
            break
        text = pytesseract.image_to_string(make(), lang=lang, config="--psm 4")
        texts.append(text)
        results.append(parse_text(text, fahrzeuge))
    return results, texts


def _consistent(results: list[BelegDaten]) -> bool:
    complete = [r for r in results if not r.fehlende_pflichtfelder()]
    if len(complete) < 2:
        return False
    a, b = complete[:2]
    return all(getattr(a, n) == getattr(b, n) for n in BelegDaten.FELDER)


@dataclass
class BelegSeite:
    datei: Path
    seite: int
    image: Image.Image | None = None
    text: str | None = None
    fehler: str | None = None

    @property
    def name(self) -> str:
        return f"{self.datei.name} (Seite {self.seite})"


def iter_belege(ordner: Path):
    files = sorted(p for p in Path(ordner).iterdir()
                   if p.is_file() and p.suffix.lower() in BELEG_ENDUNGEN)
    for path in files:
        seite = 0
        try:
            for beleg in _seiten(path):
                seite = beleg.seite
                yield beleg
        except Exception as exc:  # defekte Datei darf den Lauf nicht abbrechen
            yield BelegSeite(path, seite + 1, fehler=str(exc) or type(exc).__name__)


def _seiten(path: Path):
    if path.suffix.lower() == ".pdf":
        with pymupdf.open(path) as doc:
            for i in range(1, doc.page_count + 1):
                try:
                    page = doc[i - 1]
                    text = page.get_text()
                    if len(re.sub(r"\s", "", text)) >= MIN_TEXTLAYER_ZEICHEN:
                        beleg = BelegSeite(path, i, text=text)
                    else:
                        beleg = BelegSeite(path, i, image=_page_image(doc, page))
                except Exception as exc:  # defekte Seite: übrige Seiten trotzdem lesen
                    beleg = BelegSeite(path, i, fehler=str(exc) or type(exc).__name__)
                yield beleg
    else:
        with Image.open(path) as im:
            for i in range(getattr(im, "n_frames", 1)):
                try:
                    im.seek(i)
                    beleg = BelegSeite(path, i + 1, image=im.copy())
                except Exception as exc:
                    beleg = BelegSeite(path, i + 1, fehler=str(exc) or type(exc).__name__)
                yield beleg


def count_belege(ordner: Path) -> int:
    n = 0
    for path in Path(ordner).iterdir():
        if not path.is_file() or path.suffix.lower() not in BELEG_ENDUNGEN:
            continue
        try:
            if path.suffix.lower() == ".pdf":
                with pymupdf.open(path) as doc:
                    n += doc.page_count
            else:
                with Image.open(path) as im:
                    n += getattr(im, "n_frames", 1)
        except Exception:
            n += 1
    return n


def _page_image(doc, page) -> Image.Image:
    images = page.get_images(full=True)
    if len(images) == 1:
        info = doc.extract_image(images[0][0])
        img = Image.open(io.BytesIO(info["image"]))
        if img.width >= 1000 or img.height >= 1000:
            return img
    pix = page.get_pixmap(dpi=300)
    return Image.open(io.BytesIO(pix.tobytes("png")))


# ---------------------------------------------------------------- Ollama

def ollama_extract(text: str, fahrzeuge: FahrzeugListe, url: str = OLLAMA_URL,
                   model: str = OLLAMA_MODEL, timeout: int = 180) -> BelegDaten:
    endziffern = ", ".join(str(f.endziffer) for f in fahrzeuge.fahrzeuge if f.endziffer not in (0, None))
    prompt = (
        "Du liest den OCR-Text eines deutschen Tankbelegs. Antworte NUR mit JSON mit den Schlüsseln "
        '"kennzeichen" (z. B. "GE EL 545E"), "datum" (TT.MM.JJJJ), "menge" (Liter oder kg als Zahl), '
        '"einheit" ("l" oder "kg"), "kraftstoff_preis" (Euro-Betrag nur für Kraftstoff), '
        '"waesche_preis" (Euro-Betrag für Autowäsche, sonst null), "kilometerstand" (ganze Zahl oder null). '
        f"Unbekannte Werte als null. Gültige Kennzeichen-Endziffern: {endziffern}.\n\nOCR-Text:\n{text}"
    )
    body = json.dumps({"model": model, "prompt": prompt, "stream": False, "format": "json",
                       "options": {"temperature": 0}}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    data = json.loads(payload.get("response") or "{}")
    return _from_llm(data, fahrzeuge)


def _num(value):
    if value in (None, "", "null"):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"\d+(?:[.,]\d+)?", str(value))
    return to_float(m.group(0)) if m else None


def _from_llm(data: dict, fahrzeuge: FahrzeugListe) -> BelegDaten:
    out = BelegDaten()
    kz = data.get("kennzeichen")
    if kz:
        out.fahrzeug, out.kennzeichen_roh, _ = fahrzeuge.find_in_text(f"Kennzeichen {kz}")
        if out.fahrzeug is None:
            out.fahrzeug, _ = fahrzeuge.match_token(str(kz).split()[-1])
    if data.get("datum"):
        out.datum = parse_date(str(data["datum"]))
    out.menge = _num(data.get("menge"))
    if out.menge is not None:
        out.einheit = "kg" if str(data.get("einheit", "")).lower().startswith("k") else "l"
    out.kraftstoff_preis = _num(data.get("kraftstoff_preis"))
    out.waesche_preis = _num(data.get("waesche_preis"))
    km = _num(data.get("kilometerstand"))
    out.kilometerstand = int(km) if km else None
    return out


# ---------------------------------------------------------------- Ablauf je Beleg

def auswerten(seite: BelegSeite, fahrzeuge: FahrzeugListe, lang: str, ollama: bool,
              log=lambda msg: None) -> BelegDaten:
    if seite.text is not None:
        texts = [seite.text]
        daten = parse_text(seite.text, fahrzeuge)
    else:
        results, texts = ocr_image(seite.image, fahrzeuge, lang)
        daten = combine(results)
    fehlt = daten.fehlende_pflichtfelder()
    if ollama and (fehlt or daten.kilometerstand is None or any(h.startswith("OCR unsicher") for h in daten.hinweise)):
        log(f"{seite.name}: frage Ollama ({OLLAMA_MODEL}) ...")
        try:
            llm = ollama_extract(max(texts, key=len), fahrzeuge)
            ergaenzt = []
            for name in ("fahrzeug", "datum", "menge", "einheit", "kraftstoff_preis", "waesche_preis",
                         "kilometerstand"):
                if getattr(daten, name) is None and getattr(llm, name) is not None:
                    setattr(daten, name, getattr(llm, name))
                    ergaenzt.append(name)
            if ergaenzt:
                daten.hinweise.append("Ollama ergänzt: " + ", ".join(ergaenzt))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            daten.hinweise.append(f"Ollama nicht erreichbar/fehlerhaft: {exc}")
    return daten
