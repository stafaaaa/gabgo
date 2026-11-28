"""Prüf-Assistent: Bildausschnitte der Belege und kompaktes Fenster zum Abarbeiten der gelben Zeilen."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from pathlib import Path

import pymupdf
from PIL import Image, ImageFilter, ImageOps

from excel_vorlage import ERSTE_DATENZEILE, SHEET_EINTRAG, ExcelVorlage, VorlagenFehler, Zeile

VORSCHAU_ORDNER = "Belege_Vorschau"
VORSCHAU_DPI = 200
QUELLE_RE = re.compile(r"\(([^()]+?), Seite (\d+)\)\s*$")


# ------------------------------------------------------------------ Bildausschnitte
def _hauptbereich(profil: list[int], start: int, laenge: int) -> tuple[int, int]:
    """Bereich des Profils ohne kleine abgesetzte Flecken (Staub, Scanner-Kante): Abschnitte, die durch eine
    Lücke von mindestens 3 % getrennt, schmaler als 0,8 % der Seite sind und weniger als 2 % der dunklen
    Fläche enthalten, fallen weg. Abgesetzte Notizen wie ein handschriftlicher km-Stand sind breiter und bleiben."""
    luecke = max(len(profil) * 3 // 100, 5)
    teile, anfang, leer = [], None, 0
    for i, v in enumerate(profil + [0] * luecke):
        if v:
            if anfang is None:
                anfang = i
            leer, ende = 0, i + 1
        elif anfang is not None:
            leer += 1
            if leer >= luecke:
                teile.append((anfang, ende, sum(profil[anfang:ende])))
                anfang = None
    gesamt = sum(m for *_, m in teile) or 1
    fleck = max(laenge * 0.008, 8)
    gross = [t for t in teile if t[2] >= gesamt * 0.02 or t[1] - t[0] >= fleck] or teile
    return start + gross[0][0], start + gross[-1][1]


def zuschneiden(im: Image.Image, rand: int = 20) -> Image.Image:
    """Weiße Ränder entfernen, damit nur der Bon zu sehen ist (einzelne Staubpunkte zählen nicht)."""
    grau = ImageOps.grayscale(im)
    maske = grau.point(lambda v: 255 if v < 225 else 0).filter(ImageFilter.MedianFilter(5))
    box = maske.getbbox()
    if not box:
        return im
    l, o, r, u = box
    l, r = _hauptbereich(list(maske.crop(box).resize((r - l, 1), Image.BOX).tobytes()), l, im.width)
    o, u = _hauptbereich(list(maske.crop((l, o, r, u)).resize((1, u - o), Image.BOX).tobytes()), o, im.height)
    return im.crop((max(l - rand, 0), max(o - rand, 0), min(r + rand, im.width), min(u + rand, im.height)))


def seitenbild(datei: Path, seite: int, dpi: int = VORSCHAU_DPI) -> Image.Image:
    if datei.suffix.lower() == ".pdf":
        with pymupdf.open(datei) as doc:
            pix = doc[seite - 1].get_pixmap(dpi=dpi)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    with Image.open(datei) as im:
        im.seek(seite - 1)
        return ImageOps.exif_transpose(im.convert("RGB"))


def vorschau_name(datei: Path, seite: int) -> str:
    stamm = re.sub(r"[^\w.-]+", "_", datei.stem).strip("_") or "Beleg"
    if stamm != datei.stem or datei.suffix.lower() != ".pdf":  # „Scan 01.pdf“ und „Scan_01.jpg“ nicht vermischen
        stamm += "_" + hashlib.sha1(datei.name.encode("utf-8")).hexdigest()[:6]
    return f"{stamm}_S{seite}.png"


def vorschau_speichern(ziel: Path, datei: Path, seite: int) -> str:
    """Speichert den zugeschnittenen Beleg neben der Ziel-Datei; gibt den relativen Link zurück."""
    ordner = Path(ziel).parent / VORSCHAU_ORDNER
    ordner.mkdir(parents=True, exist_ok=True)
    name = vorschau_name(datei, seite)
    zuschneiden(seitenbild(datei, seite)).save(ordner / name, optimize=True)
    return f"{VORSCHAU_ORDNER}/{name}"


# ------------------------------------------------------------------ gelbe Zeilen lesen/speichern
@dataclass
class PruefZeile:
    zeile: int
    endziffer: object
    datum: date | None
    liter: object
    preis: float | None
    kilometerstand: int | None
    hinweis: str
    vorschau: str = ""

    def quelle(self) -> tuple[str, int] | None:
        m = QUELLE_RE.search(self.hinweis)
        return (m.group(1), int(m.group(2))) if m else None


def _hinweis_aus_zelle(v) -> tuple[str, str]:
    """(Text, Link) aus "* ..." oder =HYPERLINK("Belege_Vorschau/x.png","* ...")."""
    if not isinstance(v, str):
        return "", ""
    if v.upper().startswith("=HYPERLINK("):
        teile = [t.replace('""', '"') for t in re.findall(r'"((?:[^"]|"")*)"', v)]
        args = v[len("=HYPERLINK("):]
        erster = re.match(r'\s*((?:"(?:[^"]|"")*"\s*&?\s*)+),', args)
        n = len(re.findall(r'"((?:[^"]|"")*)"', erster.group(1))) if erster else 1
        return "".join(teile[n:]), "".join(teile[:n])
    return v, ""


def gelbe_zeilen(ziel: Path) -> list[PruefZeile]:
    import openpyxl
    wb = openpyxl.load_workbook(ziel)
    try:
        aus = []
        for n, r in enumerate(wb[SHEET_EINTRAG].iter_rows(min_row=ERSTE_DATENZEILE, max_col=8, values_only=True),
                              ERSTE_DATENZEILE):
            r = tuple(r) + (None,) * (8 - len(r))
            text, link = _hinweis_aus_zelle(r[7])
            if not text.startswith("*"):
                continue
            d = r[3].date() if isinstance(r[3], datetime) else r[3] if isinstance(r[3], date) else None
            aus.append(PruefZeile(n, r[0], d, r[4], r[5], r[6], text, link))
        return aus
    finally:
        wb.close()


def _vorschau_pfad(ziel: Path, link: str) -> Path | None:
    """Nur Links der Form Belege_Vorschau/<name>.png neben der Ziel-Datei (kein UNC-/absoluter Pfad)."""
    m = re.fullmatch(rf"{VORSCHAU_ORDNER}[/\\]([\w.-]+\.png)", link or "")
    return Path(ziel).parent / VORSCHAU_ORDNER / m.group(1) if m and ".." not in m.group(1) else None


def bild_laden(p: PruefZeile, ziel: Path, belege_ordner: Path | None) -> Image.Image | None:
    """Gespeicherter Ausschnitt, sonst die Seite aus dem Belege-Ordner (z. B. bei älteren Prüfhinweisen)."""
    bild = _vorschau_pfad(ziel, p.vorschau)
    if bild and bild.is_file():
        with Image.open(bild) as im:
            return im.convert("RGB")
    q = p.quelle()
    # nur einfache Dateinamen im Belege-Ordner, keine Netzwerk- oder absoluten Pfade aus der Arbeitsmappe
    if q and belege_ordner and re.fullmatch(r"[^\\/:]+", q[0]) and (Path(belege_ordner) / q[0]).is_file():
        try:
            return zuschneiden(seitenbild(Path(belege_ordner) / q[0], q[1]))
        except Exception:
            return None
    return None


def _zahl(text: str, ganz: bool = False):
    t = text.strip().replace("€", "").replace(" ", "")
    if not t:
        return None
    if ganz:
        t = t.replace(".", "")
    elif "," in t:
        t = t.replace(".", "").replace(",", ".")
    v = float(t)
    return int(round(v)) if ganz else v


def werte_lesen(endziffer: str, datum: str, liter: str, preis: str, km: str) -> Zeile:
    """Eingaben des Prüf-Fensters prüfen; ValueError mit verständlicher Meldung bei Fehlern."""
    e = endziffer.strip().upper()
    e = None if not e else int(e) if e.isdigit() else e
    d = None
    if datum.strip():
        for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d"):
            try:
                d = datetime.strptime(datum.strip(), fmt).date()
                break
            except ValueError:
                pass
        else:
            raise ValueError("Datum bitte als TT.MM.JJJJ eingeben.")
    l_text = liter.strip()
    try:
        l_wert = _zahl(l_text) if l_text and re.fullmatch(r"[\d.,\s]+", l_text) else (l_text or None)
        p_wert = _zahl(preis)
    except ValueError:
        raise ValueError("Liter und Preis bitte als Zahl eingeben, z. B. 56,37.") from None
    try:
        k_wert = _zahl(km, ganz=True)
    except ValueError:
        raise ValueError("Kilometerstand bitte als ganze Zahl eingeben.") from None
    return Zeile(e, d, l_wert, p_wert, k_wert)


def _in_offenem_excel_speichern(ziel: Path, n: int, z: Zeile, fz, pruefen=lambda hinweis: None) -> bool:
    """Ist die Ziel-Datei in Excel geöffnet (Windows), dort direkt ändern und speichern. False = nicht offen."""
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return False
    pythoncom.CoInitialize()
    try:
        try:
            xl = win32com.client.GetActiveObject("Excel.Application")
        except Exception:
            return False
        ziel_norm = os.path.normcase(str(Path(ziel).resolve()))
        wb = next((w for w in xl.Workbooks if os.path.normcase(str(w.FullName)) == ziel_norm), None)
        if wb is None:
            return False
        ws = wb.Worksheets(SHEET_EINTRAG)
        pruefen(str(ws.Range(f"H{n}").Value or ""))
        werte = {"A": fz.endziffer if fz else z.endziffer,
                 "D": datetime(z.datum.year, z.datum.month, z.datum.day) if z.datum else None,
                 "E": z.liter, "F": z.preis, "G": z.kilometerstand}
        try:
            for col, v in werte.items():
                if v in (None, ""):
                    ws.Range(f"{col}{n}").ClearContents()
                else:
                    ws.Range(f"{col}{n}").Value = v
            ws.Range(f"H{n}").ClearContents()
            wb.Save()
        except Exception as exc:
            raise VorlagenFehler("Excel nimmt die Änderung gerade nicht an (z. B. weil eine Zelle bearbeitet wird). "
                                 f"Bitte in Excel die Eingabe beenden und erneut speichern. ({exc})") from None
        return True
    finally:
        pythoncom.CoUninitialize()


KORREKTUREN = "korrekturen.json"


def _korrekturen_datei(ziel: Path) -> Path:
    return Path(ziel).parent / VORSCHAU_ORDNER / KORREKTUREN


def _korrektur_merken(ziel: Path, alt: PruefZeile) -> None:
    """Die ursprünglich gelesenen Werte merken, damit ein erneuter Import desselben Scans sie nicht wieder einträgt."""
    datei = _korrekturen_datei(ziel)
    try:
        daten = json.loads(datei.read_text("utf-8"))
    except (OSError, ValueError):
        daten = {}
    eintrag = [alt.endziffer, alt.datum.isoformat() if alt.datum else None, alt.liter, alt.preis]
    liste = daten.setdefault(Path(ziel).name, [])
    if eintrag not in liste:
        liste.append(eintrag)
        datei.parent.mkdir(parents=True, exist_ok=True)
        datei.write_text(json.dumps(daten, ensure_ascii=False, indent=1), "utf-8")


def korrekturen_loeschen(ziel: Path) -> None:
    """Neue Ziel-Datei: einen Korrekturverlauf einer früheren Datei gleichen Namens verwerfen."""
    datei = _korrekturen_datei(ziel)
    try:
        daten = json.loads(datei.read_text("utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(daten, dict) and daten.pop(Path(ziel).name, None) is not None:
        datei.write_text(json.dumps(daten, ensure_ascii=False, indent=1), "utf-8")


def korrekturen_laden(ziel: Path) -> list[tuple]:
    """Schlüssel (Endziffer, Datum, Liter, Preis) der im Prüf-Assistenten korrigierten Original-Werte."""
    try:
        liste = json.loads(_korrekturen_datei(ziel).read_text("utf-8")).get(Path(ziel).name, [])
        return [Zeile(e, date.fromisoformat(d) if d else None, l, p).key() for e, d, l, p in liste]
    except (OSError, ValueError, TypeError, AttributeError):
        return []


def zeile_speichern(ziel: Path, n: int, z: Zeile, erwartet: PruefZeile | None = None, log=lambda m: None) -> str:
    """Zeile n in der Ziel-Datei ersetzen und den Prüfhinweis (gelb) entfernen. erwartet: die geprüfte Zeile –
    steht dort inzwischen ein anderer Beleg (z. B. nach Sortieren), wird nichts geändert.
    Gibt "excel" (im geöffneten Excel geändert) oder "datei" zurück."""
    from verarbeitung import _ziel_sperre, pruefe_ziel_frei
    ziel = Path(ziel)

    def pruefen(hinweis):
        if erwartet is not None and (hinweis or "") != erwartet.hinweis:
            raise VorlagenFehler(f"In Excel-Zeile {n} steht nicht mehr der geprüfte Beleg (Tabelle sortiert oder "
                                 "geändert?). Bitte das Prüf-Fenster schließen und neu öffnen.")
    fz = ExcelVorlage(ziel).endziffer_bekannt(z.endziffer) if z.endziffer not in (None, "") else None
    if _in_offenem_excel_speichern(ziel, n, z, fz, pruefen):
        art = "excel"
    else:
        with _ziel_sperre(ziel, log):
            pruefe_ziel_frei(ziel)
            pruefen(next((p.hinweis for p in gelbe_zeilen(ziel) if p.zeile == n), None))
            ExcelVorlage(ziel).speichern(ziel, [], anhaengen=True, aktualisieren={n: z})  # erst unter der Sperre lesen
        art = "datei"
    if erwartet is not None and Zeile(erwartet.endziffer, erwartet.datum, erwartet.liter, erwartet.preis).key() \
            != replace(z, endziffer=fz.endziffer if fz else z.endziffer).key():
        _korrektur_merken(ziel, erwartet)
    return art


# ------------------------------------------------------------------ Fenster
class PruefFenster:
    BREITE, HOEHE = 450, 750

    def __init__(self, master, ziel: Path, belege_ordner: Path | None = None, bei_aenderung=lambda: None):
        import tkinter as tk
        from tkinter import ttk
        self.tk = tk
        self.ziel, self.belege_ordner, self.bei_aenderung = Path(ziel), belege_ordner, bei_aenderung
        self.zeilen = gelbe_zeilen(self.ziel)
        self.pos = 0
        self.bild: Image.Image | None = None
        self.zoom, self.drehung, self.auto_einpassen = 1.0, 0, True
        self._foto = None

        w = self.win = tk.Toplevel(master)
        w.title("Gelbe Belege prüfen")
        faktor = max(w.winfo_fpixels("1i") / 96, 1.0)  # Windows-Skalierung 125 %/150 %: Fenster mitwachsen lassen
        breite = min(round(self.BREITE * faktor), w.winfo_screenwidth())
        h = min(round(self.HOEHE * faktor), w.winfo_screenheight() - round(80 * faktor))
        x = max(w.winfo_screenwidth() - breite - 10, 0)
        w.geometry(f"{breite}x{h}+{x}+10")
        w.attributes("-topmost", True)
        w.minsize(round(360 * faktor), round(500 * faktor))
        self.titel = tk.StringVar()
        ttk.Label(w, textvariable=self.titel, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=8, pady=(6, 0))
        self.hinweis = ttk.Label(w, wraplength=breite - 20, foreground="#8a5a00")
        self.hinweis.pack(anchor="w", padx=8)
        w.bind("<Configure>", lambda e: e.widget is w and self.hinweis.configure(wraplength=max(e.width - 20, 100)))
        # Felder und Knöpfe zuerst von unten packen, damit bei wenig Platz nur das Bild kleiner wird
        knoepfe = ttk.Frame(w)
        knoepfe.pack(side="bottom", fill="x", padx=8, pady=(0, 8))
        form = ttk.Frame(w)
        form.pack(side="bottom", fill="x", padx=8, pady=6)
        werkzeug = ttk.Frame(w)
        werkzeug.pack(side="bottom", fill="x", padx=8)
        self.canvas = tk.Canvas(w, background="#d9d9d9", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=8, pady=4)
        ttk.Button(werkzeug, text="⟳ Drehen", command=self._drehen).pack(side="left")
        ttk.Button(werkzeug, text="Einpassen", command=self._einpassen).pack(side="left", padx=4)
        ttk.Label(werkzeug, text="Mausrad: Zoom", foreground="#666").pack(side="right")

        form.columnconfigure(1, weight=1)
        self.felder = {}
        for i, (key, label) in enumerate([("endziffer", "Endziffer"), ("datum", "Datum (TT.MM.JJJJ)"),
                                          ("liter", "Liter"), ("preis", "Preis (€)"),
                                          ("km", "Kilometerstand")]):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky="w", pady=1)
            var = tk.StringVar()
            e = ttk.Entry(form, textvariable=var)
            e.grid(row=i, column=1, sticky="ew", padx=(6, 0), pady=1)
            e.bind("<Return>", lambda _e: self._speichern())
            self.felder[key] = var
        self.speichern_btn = ttk.Button(knoepfe, text="Speichern & Nächster", command=self._speichern)
        self.speichern_btn.pack(side="left")
        ttk.Button(knoepfe, text="Überspringen", command=self._weiter).pack(side="left", padx=4)
        ttk.Button(knoepfe, text="Schließen", command=w.destroy).pack(side="right")

        self.canvas.bind("<Configure>", lambda _e: self._einpassen() if self.auto_einpassen else self._zeichnen())
        self.canvas.bind("<MouseWheel>", lambda e: self._zoomen(1.15 if e.delta > 0 else 1 / 1.15))
        self.canvas.bind("<Button-4>", lambda _e: self._zoomen(1.15))
        self.canvas.bind("<Button-5>", lambda _e: self._zoomen(1 / 1.15))
        self.canvas.bind("<ButtonPress-1>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind("<B1-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self._laden()

    # Anzeige
    def _laden(self):
        if self.pos >= len(self.zeilen):
            self.titel.set("Keine gelben Belege mehr – alles geprüft.")
            self.hinweis.configure(text="")
            self.bild = None
            self.canvas.delete("all")
            self.speichern_btn.configure(state="disabled")
            for var in self.felder.values():
                var.set("")
            return
        p = self.zeilen[self.pos]
        self.titel.set(f"Beleg {self.pos + 1} von {len(self.zeilen)} – Excel-Zeile {p.zeile}")
        self.hinweis.configure(text=p.hinweis.removeprefix("* "))
        def zahl(v, stellen=2):
            return "" if v is None else v if isinstance(v, str) else f"{v:.{stellen}f}".replace(".", ",")
        self.felder["endziffer"].set("" if p.endziffer is None else str(p.endziffer))
        self.felder["datum"].set(p.datum.strftime("%d.%m.%Y") if p.datum else "")
        self.felder["liter"].set(zahl(p.liter))
        self.felder["preis"].set(zahl(p.preis))
        self.felder["km"].set("" if p.kilometerstand is None else str(int(p.kilometerstand)))
        self.bild = bild_laden(p, self.ziel, self.belege_ordner)
        self.drehung = 0
        self.auto_einpassen = True  # bis zum ersten Zoomen der Fenstergröße folgen (auch beim ersten Anzeigen)
        self._einpassen()

    def _einpassen(self):
        if self.bild is None:
            return self._zeichnen()
        b = self._gedreht()
        cw, ch = max(self.canvas.winfo_width(), 50), max(self.canvas.winfo_height(), 50)
        self.zoom = min(cw / b.width, ch / b.height)
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self._zeichnen()

    def _gedreht(self) -> Image.Image:
        return self.bild.rotate(-self.drehung, expand=True) if self.drehung else self.bild

    def _zeichnen(self):
        from PIL import ImageTk
        self.canvas.delete("all")
        if self.bild is None:
            self.canvas.create_text(self.canvas.winfo_width() // 2, 40, text="Kein Bild zum Beleg gefunden")
            return
        b = self._gedreht()
        groesse = (max(int(b.width * self.zoom), 1), max(int(b.height * self.zoom), 1))
        self._foto = ImageTk.PhotoImage(b.resize(groesse, Image.LANCZOS))
        self.canvas.create_image(0, 0, anchor="nw", image=self._foto)
        self.canvas.configure(scrollregion=(0, 0) + groesse)

    def _zoomen(self, faktor):
        if self.bild is not None:
            self.auto_einpassen = False
            self.zoom = min(max(self.zoom * faktor, 0.05), 6.0)
            self._zeichnen()

    def _drehen(self):
        if self.bild is not None:
            self.drehung = (self.drehung + 90) % 360
            self._einpassen()

    # Aktionen
    def _weiter(self):
        self.pos += 1
        self._laden()

    def _speichern(self):
        from tkinter import messagebox
        if self.pos >= len(self.zeilen):
            return
        f = {k: v.get() for k, v in self.felder.items()}
        try:
            z = werte_lesen(f["endziffer"], f["datum"], f["liter"], f["preis"], f["km"])
            zeile_speichern(self.ziel, self.zeilen[self.pos].zeile, z, erwartet=self.zeilen[self.pos])
        except (ValueError, VorlagenFehler, OSError) as exc:
            return messagebox.showerror("Nicht gespeichert", str(exc), parent=self.win)
        self.bei_aenderung()
        self._weiter()
