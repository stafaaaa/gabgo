"""Texterkennung und Auswertung gescannter Tankbelege."""
from __future__ import annotations

import io
import os
import re
import shutil
import sys
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
    r"premium|kraftstoff|autogas|\blpg\b|\bcng\b|erdgas|\bhvo\b|bleifrei|bio-?\s?methan|"
    r"\bgas\b|[hl]-gas|fl[üu]e?ssiggas",
    re.I,
)
ADBLUE = re.compile(r"ad\s?blue|\bdef\b|harnstoff", re.I)
WASH_WORDS = re.compile(r"w[äa]e?sche|wasch|\bwash|glanz|pflegeprogramm", re.I)
WAESCHE = "Wäsche"
# Bezahlte Positionen außer Kraftstoff; Reihenfolge: spezifische Begriffe zuerst ("Scheibenwaschmittel").
POSTEN_ARTEN = [
    ("Wischwasser", re.compile(r"wisch\s*wasser|scheiben\s*-?\s*(?:reinig|klar|frost|wasch)|frostschutz|"
                               r"screen\s?wash", re.I)),
    (WAESCHE, WASH_WORDS),
    ("AdBlue", ADBLUE),
    ("Motoröl", re.compile(r"motor\s*-?\s*[öo]e?l|\b[öo]e?l\b|\b\d{1,2}w-?\d{2}\b", re.I)),
    ("Pflege", re.compile(r"pflege|reinig|staubsaug|\bsauger\b|politur|cockpit", re.I)),
    ("Zubehör", re.compile(r"zubeh[öo]r|scheibenwischer|wischerbl|enteiser|eiskratzer|gl[üu]hlampe|"
                           r"leuchtmittel", re.I)),
]
KEIN_POSTEN = re.compile(r"rabatt|gutschein|bonus|payback|punkte|storno|mwst|\bust\b|netto|steuer|pfand", re.I)
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


def betraege(line: str) -> list[float]:
    """Euro-Beträge einer Zeile ohne Mengen (l/kg) und Stück-/Literpreise."""
    return [v for v, m in ((to_float(m.group(1)), m) for m in re.finditer(AMOUNT, line))
            if not re.match(r"\s*(?:€|EUR|E)?\s*/", line[m.end():])
            and not re.match(r"\s*(?:l|liter|ltr|kg)\b", line[m.end():], re.I)]


def posten_art(line: str) -> str | None:
    for art, rx in POSTEN_ARTEN:
        if rx.search(line):
            return art
    return None


PLATE_GENERIC = re.compile(r"\b([A-ZÄÖÜ]{1,3})[\s-]+([A-Z]{1,2})[\s-]*(\d{1,4}\s?[EH]?)\b")


@dataclass
class Fahrzeug:
    endziffer: object
    kennzeichen: str
    fahrer: str
    neu: bool = False  # vom Import in "Liste KfZ_Fahrer" ergänzt


class FahrzeugListe:
    def __init__(self, fahrzeuge: list[Fahrzeug], reserve: "FahrzeugListe | None" = None):
        self.fahrzeuge = fahrzeuge
        # Unbekannte Fahrzeuge anlegen statt Beleg verwerfen; reserve = Liste der festen Vorlage
        self.neu_erlaubt = False
        self.reserve = reserve
        self.neue: list[Fahrzeug] = []
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

    def _neu_anlegen(self, cand: str, text: str) -> Fahrzeug | None:
        """Fahrzeug, das nicht in der Liste steht: aus der festen Vorlage übernehmen oder sauber gelesen neu anlegen."""
        vorlage, _ = self.reserve.match_token(cand, fuzzy=False) if self.reserve else (None, None)
        t = re.sub(r"\s", "", cand).upper().replace("€", "E").replace("£", "E")
        if vorlage is None and not re.fullmatch(r"\d{2,4}[EH]?", t):
            return None
        if vorlage is not None:
            fz = Fahrzeug(vorlage.endziffer, vorlage.kennzeichen, vorlage.fahrer, neu=True)
        else:
            fz = Fahrzeug(int(t) if t.isdigit() else t, _kennzeichen_zu(t, text), "Neu", neu=True)
        key = self._norm(fz.endziffer)
        if key in self.keys:
            return self.keys[key]
        self.fahrzeuge.append(fz)
        self.keys[key] = fz
        self.neue.append(fz)
        return fz

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
        alternativen: dict[str, str] = {}
        for line in text.splitlines():
            m = PLATE_WORDS.search(line)
            if not m:
                continue
            rest = line[m.end():]
            rest = re.sub(r"^[\w-]*?(z?eichen|nummer|nr\.?)\b", "", rest, flags=re.I)
            tokens = re.findall(r"[A-Za-z0-9€£|$!]+", rest)
            while tokens and tokens[0].isalpha() and len(tokens[0]) <= 3 and tokens[0].upper() == tokens[0]:
                tokens.pop(0)
            if tokens:
                nach = tokens[1] if len(tokens) > 1 and len(tokens[1]) == 1 else ""
                if nach.isalpha() or nach in ("€", "£"):
                    candidates.append(tokens[0] + nach)
                elif nach in E_LIKE:  # Ziffer: verlesenes E oder z. B. Zapfsäulennummer
                    alternativen[tokens[0]] = tokens[0] + "E"
                candidates.append(tokens[0])
        candidates += [m.group(1) for m in PLATE_ANYWHERE.finditer(text)]
        for fuzzy in (False, True):
            if fuzzy and self.neu_erlaubt:
                for cand in candidates:
                    fz = self._neu_anlegen(cand, text)
                    if fz:
                        return fz, cand, None
            for cand in candidates:
                fz, note = self.match_token(cand, fuzzy)
                if fz:
                    alt = self.keys.get(alternativen.get(cand, ""))
                    if alt is not None and alt is not fz:
                        note = ((note + "; ") if note else "") + (
                            f"unsicher: Kennzeichen könnte auch '{alt.endziffer}' sein (statt '{fz.endziffer}')")
                    return fz, cand, note
        return None, (candidates[0] if candidates else None), None


def _kennzeichen_zu(endziffer: str, text: str) -> str:
    for m in PLATE_ANYWHERE.finditer(text):
        if re.sub(r"\s", "", m.group(1)).upper().replace("€", "E") == endziffer:
            mitte = re.match(r"[GC6][EF€]\s*[-.\s]\s*([EL])", m.group(0)).group(1)
            return f"GE {'EL' if mitte == 'E' else 'LE'} {endziffer}"
    for m in PLATE_GENERIC.finditer(text.upper()):
        if m.group(3).replace(" ", "") == endziffer:
            return f"{m.group(1)} {m.group(2)} {endziffer}"
    return ""


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
    posten: tuple = ()  # ((Art, Betrag), ...) z. B. ("AdBlue", 8.99) – alles außer Kraftstoff und Wäsche
    hinweise: list[str] = field(default_factory=list)
    preis_abgeleitet: bool = False

    FELDER = ("fahrzeug", "datum", "menge", "einheit", "kraftstoff_preis", "waesche_preis",
              "kilometerstand", "summe", "posten")

    @property
    def hat_kraftstoff(self) -> bool:
        return self.menge is not None

    @property
    def hat_waesche(self) -> bool:
        return self.waesche_preis is not None and self.waesche_preis > 0

    def erfasst(self) -> float:
        """Summe aller als Zeile erfassten Beträge."""
        return round((self.kraftstoff_preis or 0) + (self.waesche_preis if self.hat_waesche else 0)
                     + sum(p for _, p in self.posten), 2)

    def rest(self) -> float | None:
        """Betrag laut Summe, der keiner Zeile zugeordnet ist (None = keine Summe erkannt)."""
        return None if self.summe is None else round(self.summe - self.erfasst(), 2)

    def fehlende_pflichtfelder(self) -> list[str]:
        fehlt = []
        if self.fahrzeug is None:
            fehlt.append("Endziffer/Kennzeichen")
        if self.datum is None:
            fehlt.append("Datum")
        if not self.hat_kraftstoff and not self.hat_waesche and not self.posten:
            fehlt.append("Kraftstoff, Wäsche oder sonstiger Posten")
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

    summen, benutzt = _posten(lines)
    daten.waesche_preis = summen.pop(WAESCHE, None)
    daten.posten = tuple(summen.items())

    def sonstiger_posten(zeile: str) -> bool:
        art = posten_art(zeile)
        return art is not None and art != WAESCHE and not _ist_kraftstoffzeile(zeile, art)

    fuel_lines = []
    for i, line in enumerate(lines):
        # Zeile nach Zusatzartikel: Stückpreis oder Gebindegröße ohne Betrag gehört zum Artikel
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        menge_vor_kraftstoff = FUEL_WORDS.search(nxt) and not QTY.search(nxt)
        zum_posten = (UNIT_PRICE.search(line) and not QTY.search(line)) or (
            not betraege(line) and not menge_vor_kraftstoff)
        if (i in benutzt and not WASH_WORDS.search(line)) or sonstiger_posten(line) or (
                i and sonstiger_posten(lines[i - 1]) and zum_posten and not FUEL_WORDS.search(line)):
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
            price = round(daten.summe - (daten.waesche_preis or 0) - sum(p for _, p in daten.posten), 2)
            daten.hinweise.append("Kraftstoffpreis aus Summe abgeleitet")
            daten.preis_abgeleitet = True
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


def _ist_kraftstoffzeile(line: str, art: str | None) -> bool:
    """Kraftstoffzeile mit Menge, die nur nebenbei ein Postenwort enthält ("Super E10 Pflegeformel")."""
    return art not in ("AdBlue", "Motoröl", "Wischwasser") and bool(FUEL_WORDS.search(line) and QTY.search(line))


def _posten(lines: list[str]) -> tuple[dict[str, float], set[int]]:
    """Bezahlte Positionen außer Kraftstoff: {Art: Betrag} und die dafür gelesenen Zeilen."""
    gesehen: dict[str, list[tuple[float, set[str]]]] = {}
    benutzt: set[int] = set()
    for i, line in enumerate(lines):
        art = posten_art(line)
        if not art or i in benutzt or KEIN_POSTEN.search(line) or TOTAL_WORDS.search(line):
            continue
        if (art == WAESCHE and QTY.search(line)) or _ist_kraftstoffzeile(line, art):
            continue
        alle = betraege(line)
        vals = [v for v in alle if v > 0]
        zeilen = {i}
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if (not alle and nxt and not posten_art(nxt) and not TOTAL_WORDS.search(nxt)
                and not FUEL_WORDS.search(nxt) and not KEIN_POSTEN.search(nxt)):
            # Werbung ("Autowäsche geöffnet", "Wäsche ab 9,99 €/St") ist keine gekaufte Wäsche
            if art != WAESCHE or not (re.search(r"/\s*st", nxt, re.I) or QTY.search(nxt) or UNIT_PRICE.search(nxt)):
                vals = [v for v in betraege(nxt) if v > 0]
                zeilen.add(i + 1)
        if vals:
            # Viele Bons listen eine Position zweimal (Kopf + Artikelzeile): gleicher Betrag zählt einmal
            # gleicher Betrag zählt nur einmal, wenn auch das Produktwort gleich ist
            # ("Wash Glanzwäsche € 11,49" / "0082 Glanzwäsche 11,49"), nicht bei Innenreinigung + Staubsauger
            woerter = set()
            for z in zeilen:
                ws = [w for w in re.findall(r"[^\W_]+", lines[z].lower().replace("-", "")) if not w.isdigit()]
                woerter |= {w for w in ws if len(w) >= 4} | {a + b for a, b in zip(ws, ws[1:])}  # "Ad Blue" = "AdBlue"
            liste = gesehen.setdefault(art, [])
            if not any(v == vals[-1] and w & woerter for v, w in liste):
                liste.append((vals[-1], woerter))
            benutzt |= zeilen
    return {art: round(sum(v for v, _ in werte), 2) for art, werte in gesehen.items()}, benutzt


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
    out.preis_abgeleitet = any(r.preis_abgeleitet and r.kraftstoff_preis == out.kraftstoff_preis for r in results)
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
    if isinstance(v, tuple):
        return " + ".join(f"{a} {p:.2f}" for a, p in v) or "keine"
    return str(v)


# ---------------------------------------------------------------- OCR

def configure_tesseract() -> str | None:
    import pytesseract
    mitgeliefert = Path(sys.executable).parent / "tesseract" / "tesseract.exe" if getattr(sys, "frozen", False) else None
    for cand in (os.environ.get("TESSERACT_CMD"), mitgeliefert, TESSERACT_WINDOWS, shutil.which("tesseract")):
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

    @property
    def quelle(self) -> str:
        return f"{self.datei.name} | Seite {self.seite}"


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


# ---------------------------------------------------------------- KI (Ollama, OpenRouter, ...)

POSTEN_NAMEN = [a for a, _ in POSTEN_ARTEN if a != WAESCHE]


def ki_prompt(text: str | None, fahrzeuge: FahrzeugListe, mit_bild: bool) -> str:
    endziffern = ", ".join(str(f.endziffer) for f in fahrzeuge.fahrzeuge if f.endziffer not in (0, None))
    quelle = "das Bild eines deutschen Tankbelegs" if mit_bild else "den OCR-Text eines deutschen Tankbelegs"
    prompt = (
        f"Du liest {quelle}. Antworte NUR mit JSON mit den Schlüsseln "
        '"kennzeichen" (z. B. "GE EL 545E"), "datum" (TT.MM.JJJJ), "menge" (getankte Liter oder kg als Zahl, '
        'auch Gas wie CNG/LPG), "einheit" ("l" oder "kg"), "kraftstoff_preis" (Euro-Betrag nur für Kraftstoff), '
        '"waesche_preis" (Euro-Betrag für Autowäsche, sonst null), '
        f'"posten" (Liste weiterer bezahlter Fahrzeug-Positionen als {{"art": eine von {", ".join(POSTEN_NAMEN)}, '
        '"preis": Euro-Betrag}, sonst []), "summe" (Gesamtbetrag), "kilometerstand" (ganze Zahl oder null). '
        "Unbekannte Werte als null, keine 0-Beträge erfinden. "
        f"Bekannte Kennzeichen-Endziffern: {endziffern}."
    )
    if text:
        prompt += f"\n\nOCR-Text (kann Fehler enthalten):\n{text}"
    return prompt


def ollama_extract(text: str, fahrzeuge: FahrzeugListe, url: str = OLLAMA_URL,
                   model: str = OLLAMA_MODEL, timeout: int = 180) -> BelegDaten:
    import ki_anbieter
    return ki_anbieter.frage_ki(ki_anbieter.KiEinstellung("ollama", model, url=url, bild=False),
                                text, None, fahrzeuge, timeout)


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
    out.menge = _num(data.get("menge")) or None
    if out.menge is not None:
        out.einheit = "kg" if str(data.get("einheit", "")).lower().startswith("k") else "l"
    out.kraftstoff_preis = _num(data.get("kraftstoff_preis"))
    out.waesche_preis = _num(data.get("waesche_preis")) or None
    out.summe = _num(data.get("summe")) or None
    summen: dict[str, float] = {}
    for p in data.get("posten") or []:
        if not isinstance(p, dict):
            continue
        preis = _num(p.get("preis"))
        art = posten_art(str(p.get("art", ""))) or next(
            (a for a in POSTEN_NAMEN if a.lower() == str(p.get("art", "")).strip().lower()), None)
        if not preis or preis <= 0 or art is None:
            continue
        if art == WAESCHE:
            out.waesche_preis = round((out.waesche_preis or 0) + preis, 2)
        else:
            summen[art] = round(summen.get(art, 0) + preis, 2)
    out.posten = tuple(summen.items())
    km = _num(data.get("kilometerstand"))
    out.kilometerstand = int(km) if km else None
    return out


# ---------------------------------------------------------------- Ablauf je Beleg

def seitenbild(seite: BelegSeite) -> Image.Image | None:
    """Seitenbild für Vision-Modelle, bei PDFs mit Textschicht frisch gerendert."""
    if seite.image is not None or seite.datei.suffix.lower() != ".pdf":
        return seite.image
    try:
        with pymupdf.open(seite.datei) as doc:
            pix = doc[seite.seite - 1].get_pixmap(dpi=150)  # ganze Seite, nicht nur eingebettete Grafik
            return Image.open(io.BytesIO(pix.tobytes("png")))
    except Exception:
        return None


def auswerten(seite: BelegSeite, fahrzeuge: FahrzeugListe, lang: str, ki=None,
              log=lambda msg: None) -> BelegDaten:
    """ki: None/False = nur OCR, True = Ollama (Standard), sonst ki_anbieter.KiEinstellung."""
    import ki_anbieter
    if seite.text is not None:
        texts = [seite.text]
        daten = parse_text(seite.text, fahrzeuge)
    else:
        results, texts = ocr_image(seite.image, fahrzeuge, lang)
        daten = combine(results)
    ki = ki_anbieter.KiEinstellung.aus_wert(ki)
    rest = daten.rest()
    unklar = (daten.fehlende_pflichtfelder() or daten.kilometerstand is None or (rest is not None and abs(rest) > 0.02)
              or any(h.startswith("OCR unsicher") for h in daten.hinweise))
    if ki.aktiv and unklar:
        bild = seitenbild(seite) if ki.bild else None
        log(f"{seite.name}: frage {ki.beschreibung()}{' mit Seitenbild' if bild is not None else ''} ...")
        try:
            llm = ki_anbieter.frage_ki(ki, max(texts, key=len), bild, fahrzeuge)
        except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            daten.hinweise.append(f"KI ({ki.beschreibung()}) nicht erreichbar/fehlerhaft: {exc}")
            return daten
        ergaenzt, korrigiert = [], []
        for name in ("fahrzeug", "datum", "menge", "einheit", "kraftstoff_preis", "waesche_preis",
                     "kilometerstand", "summe"):
            alt, neu = getattr(daten, name), getattr(llm, name)
            if neu is None:
                continue
            if alt is None:
                setattr(daten, name, neu)
                ergaenzt.append(name)
            elif neu != alt and any(h.startswith(f"OCR unsicher bei {name}:") for h in daten.hinweise):
                setattr(daten, name, neu)
                korrigiert.append(f"{name} {_fmt(alt)} -> {_fmt(neu)}")
        vorhanden = {a for a, _ in daten.posten}
        dazu = tuple(p for p in llm.posten if p[0] not in vorhanden)
        if dazu:
            daten.posten += dazu
            ergaenzt.append("posten " + _fmt(dazu))
            rest = daten.rest()
            if (rest is not None and rest < -0.02 and daten.kraftstoff_preis is not None
                    and daten.preis_abgeleitet):
                # Kraftstoffpreis war aus der Summe abgeleitet und enthielt die neuen Posten schon
                neu = llm.kraftstoff_preis or round(daten.kraftstoff_preis + rest, 2)
                if neu > 0:
                    korrigiert.append(f"kraftstoff_preis {_fmt(daten.kraftstoff_preis)} -> {_fmt(neu)}")
                    daten.kraftstoff_preis = neu
        if ergaenzt:
            daten.hinweise.append("KI ergänzt: " + ", ".join(ergaenzt))
        if korrigiert:
            daten.hinweise.append("KI korrigiert unsichere OCR: " + ", ".join(korrigiert))
    return daten
