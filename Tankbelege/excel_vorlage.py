"""Hängt Zeilen an "Tabelle6" an, ohne Aufbau oder Design der Vorlage zu verändern.

Die .xlsx wird auf XML-Ebene bearbeitet: Alle Teile der Vorlage werden unverändert
übernommen, nur Zeilen, Tabellenbereich und die zugehörigen Verweise werden ergänzt.
"""
from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import openpyxl

from belege_core import Fahrzeug, FahrzeugListe

SHEET_LISTE = "Liste KfZ_Fahrer"
SHEET_EINTRAG = "Eintragungen"
TABELLE = "Tabelle6"
SPALTEN = ["Endziffer", "Kfz", "Fahrer", "Datum", "Liter", "Preis", "Kilometerstand"]
WAESCHE = "Wäsche"
ERSTE_DATENZEILE = 3
PRUEF_TITEL = "Prüfhinweis"
PRUEF_FORMEL = 'LEFT($H3,1)="*"'
PRUEF_FARBE = "FFFFF2CC"  # hellgelb
# Elemente, die im Arbeitsblatt-XML nach <conditionalFormatting> stehen müssen
NACH_BEDINGT = ("dataValidations", "hyperlinks", "printOptions", "pageMargins", "pageSetup", "headerFooter",
                "rowBreaks", "colBreaks", "customProperties", "cellWatches", "ignoredErrors", "smartTags",
                "drawing", "legacyDrawing", "legacyDrawingHF", "picture", "oleObjects", "controls",
                "webPublishItems", "tableParts", "extLst")

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "pr": "http://schemas.openxmlformats.org/package/2006/relationships"}
ROW_RE = re.compile(r'<row r="(\d+)"[^>]*?(?:/>|>.*?</row>)', re.S)
CELL_RE = re.compile(r'<c r="([A-Z]+)(\d+)"([^>]*?)(?:/>|>(.*?)</c>)', re.S)


class VorlagenFehler(Exception):
    pass


@dataclass
class Zeile:
    endziffer: object  # None = nicht erkannt
    datum: date | None
    liter: object  # float, "Wäsche" o. Ä. oder None (nicht erkannt)
    preis: float | None
    kilometerstand: int | None = None
    quelle: str = ""
    pruefhinweis: str = ""  # Spalte H, z. B. "* Bitte prüfen/vervollständigen: ..."

    def key(self):
        liter = self.liter if self.liter is None or isinstance(self.liter, str) else round(float(self.liter), 2)
        preis = None if self.preis is None else round(float(self.preis), 2)
        return ("" if self.endziffer is None else str(self.endziffer).upper(), self.datum, liter, preis)


def _excel_serial(d: date) -> int:
    return (d - date(1899, 12, 30)).days


def _num(v) -> str:
    if isinstance(v, int) or (isinstance(v, float) and v.is_integer() and abs(v) > 1000):
        return str(int(v))
    return repr(round(float(v), 2))


class ExcelVorlage:
    def __init__(self, path: Path):
        self.path = Path(path)
        with zipfile.ZipFile(self.path) as z:
            self.infos = z.infolist()
            self.parts = {i.filename: z.read(i.filename) for i in self.infos}
        self._locate()
        self._read_values()

    # ---------------------------------------------------------- Struktur
    def _rels(self, part: str) -> dict[str, str]:
        rels_name = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
        if rels_name not in self.parts:
            return {}
        root = ET.fromstring(self.parts[rels_name])
        base = posixpath.dirname(part)
        def ziel(t: str) -> str:  # absolute Ziele ("/xl/...") z. B. nach Speichern mit openpyxl
            return t.lstrip("/") if t.startswith("/") else posixpath.normpath(posixpath.join(base, t))
        return {r.get("Id"): ziel(r.get("Target")) for r in root.findall("pr:Relationship", NS)}

    def _locate(self):
        wb = ET.fromstring(self.parts["xl/workbook.xml"])
        rels = self._rels("xl/workbook.xml")
        sheets = [(s.get("name"), rels[s.get(f"{{{NS['r']}}}id")]) for s in wb.find("m:sheets", NS)]
        names = [n for n, _ in sheets]
        for needed in (SHEET_LISTE, SHEET_EINTRAG):
            if needed not in names:
                raise VorlagenFehler(f"Blatt '{needed}' fehlt in der Vorlage.")
        self.sheet_index = names.index(SHEET_EINTRAG) + 1
        self.sheet_part = dict(sheets)[SHEET_EINTRAG]
        self.liste_part = dict(sheets)[SHEET_LISTE]
        self.table_part = None
        for target in self._rels(self.sheet_part).values():
            if "/tables/" in target:
                t = ET.fromstring(self.parts[target])
                if t.get("name") == TABELLE or t.get("displayName") == TABELLE:
                    self.table_part = target
                    cols = [c.get("name") for c in t.find("m:tableColumns", NS)]
                    if cols not in (SPALTEN, SPALTEN + [PRUEF_TITEL]):
                        raise VorlagenFehler(f"Spalten von {TABELLE} weichen ab: {cols}")
                    self.table_ref = t.get("ref")
                    if int(t.get("totalsRowCount", "0") or 0) > 0:
                        raise VorlagenFehler(f"{TABELLE} hat eine Ergebniszeile – bitte in Excel ausschalten "
                                             "(Tabellenentwurf → Ergebniszeile), dann erneut starten.")
        if not self.table_part:
            raise VorlagenFehler(f"Tabelle '{TABELLE}' nicht im Blatt '{SHEET_EINTRAG}' gefunden.")
        wb_rels = rels.values()
        self.shared_part = next((p for p in wb_rels if p.endswith("sharedStrings.xml")), None)
        self.styles_part = next((p for p in wb_rels if p.endswith("styles.xml")), None)
        self.calc_part = next((p for p in wb_rels if p.endswith("calcChain.xml")), None)

    def _read_values(self):
        wb = openpyxl.load_workbook(self.path, read_only=True, data_only=False)
        self.fahrzeuge = FahrzeugListe([
            Fahrzeug(r[0], r[1], r[2])
            for r in wb[SHEET_LISTE].iter_rows(min_row=2, max_col=3, values_only=True)
            if r and r[0] not in (None, "")
        ])
        self.vorhandene: set = set()  # vollständige Einträge (Endziffer und Datum)
        self.eintraege: list[tuple] = []  # alle Einträge, auch unvollständige
        self.eintrag_zeilen: list[tuple] = []  # (Excel-Zeile, Schlüssel, Kilometerstand)
        rows = wb[SHEET_EINTRAG].iter_rows(min_row=ERSTE_DATENZEILE, max_col=7, values_only=True)
        for n, r in enumerate(rows, ERSTE_DATENZEILE):
            if not r:
                continue
            r = tuple(r) + (None,) * (7 - len(r))
            d = r[3].date() if isinstance(r[3], datetime) else r[3]
            if not isinstance(d, date):
                d = None
            if all(v in (None, "") for v in (r[0], d, r[4], r[5], r[6])):
                continue
            liter = r[4] if r[4] is None or isinstance(r[4], str) else float(r[4])
            preis = None if r[5] in (None, "") else float(r[5])
            key = Zeile(None if r[0] in (None, "") else r[0], d, liter, preis).key()
            self.eintraege.append(key)
            km = r[6] if isinstance(r[6], (int, float)) and not isinstance(r[6], bool) else None
            self.eintrag_zeilen.append((n, key, km))
            if r[0] not in (None, "") and d is not None:
                self.vorhandene.add(key)
        wb.close()

    def endziffer_bekannt(self, value) -> Fahrzeug | None:
        return self.fahrzeuge.keys.get(FahrzeugListe._norm(value))

    # ---------------------------------------------------------- Schreiben
    def speichern(self, ziel: Path, zeilen: list[Zeile], anhaengen: bool = False,
                  neue_fahrzeuge: list[Fahrzeug] = (), ergaenzen: dict | None = None) -> list[int]:
        """anhaengen=True: self.path ist eine bereits erzeugte Ausgabe und wird fortgeschrieben.
        neue_fahrzeuge werden am Ende von "Liste KfZ_Fahrer" ergänzt.
        ergaenzen: {Excel-Zeile: Zeile} – vorhandene Einträge ohne Endziffer um Endziffer, km und Prüfhinweis ergänzen."""
        ziel = Path(ziel)
        if ziel.suffix.lower() != ".xlsx":
            raise VorlagenFehler("Ziel muss eine .xlsx-Datei sein.")
        if ziel.resolve() == self.path.resolve() and not anhaengen:
            raise VorlagenFehler("Die Originalvorlage darf nicht überschrieben werden.")
        parts = dict(self.parts)
        strings = _SharedStrings(parts.get(self.shared_part)) if self.shared_part else None
        liste_ende = self._liste_erweitern(parts, list(neue_fahrzeuge), strings) if neue_fahrzeuge else 0
        sheet = parts[self.sheet_part].decode("utf-8")

        for n, z in sorted((ergaenzen or {}).items(), reverse=True):
            m = next((m for m in ROW_RE.finditer(sheet) if int(m.group(1)) == n), None)
            if m is not None:
                sheet = sheet[:m.start()] + self._zeile_ergaenzen(m.group(0), n, z, strings) + sheet[m.end():]
        rows = {int(m.group(1)): m for m in ROW_RE.finditer(sheet)}
        if 2 not in rows:
            raise VorlagenFehler("Vorlagezeile 2 fehlt im Blatt 'Eintragungen'.")
        tmpl_row = rows[2].group(0)
        formulas = {}
        for m in CELL_RE.finditer(tmpl_row):
            f = re.search(r"<f>(.*?)</f>", m.group(4) or "", re.S)
            if m.group(1) in ("B", "C") and f:
                style = re.search(r'\ss="\d+"', m.group(3))
                formulas[m.group(1)] = (f.group(1), style.group(0) if style else "")
        if set(formulas) != {"B", "C"}:
            raise VorlagenFehler("VLOOKUP-Formeln in B2/C2 fehlen.")
        row_attrs = re.match(r"<row ([^>]*?)/?>", tmpl_row).group(1)
        row_attrs = " ".join(a for a in re.findall(r'[\w:]+="[^"]*"', row_attrs)
                             if a.split("=")[0] in ("spans", "x14ac:dyDescent"))

        filled = [n for n, m in rows.items() if n >= 2 and _has_values(m.group(0))]
        start = max(filled + [2]) + 1
        # Zeilen unterhalb der Daten: Inhalte außerhalb A:G (z. B. Notizen) bleiben erhalten.
        later = {n: rows[n].group(0) for n in rows if n >= start}
        removable = [n for n, xml in later.items() if not _fremde_zellen(xml)]
        for n in sorted(later, reverse=True):
            m = rows[n]
            sheet = sheet[:m.start()] + sheet[m.end():]

        date_style = self._date_style(parts)
        new_xml, numbers = [], []
        for i, z in enumerate(zeilen):
            n = start + i
            numbers.append(n)
            fz = self.endziffer_bekannt(z.endziffer) if z.endziffer not in (None, "") else None
            cells = []
            if fz or z.endziffer not in (None, ""):
                cells.append(self._value_cell(f"A{n}", fz.endziffer if fz else z.endziffer, strings))
            for col, idx in (("B", 1), ("C", 2)):
                f, style = formulas[col]
                if fz:
                    cached = fz.kennzeichen if idx == 1 else fz.fahrer
                    cells.append(f'<c r="{col}{n}"{style} t="str"><f>{f}</f><v>{escape(str(cached))}</v></c>')
                else:
                    cells.append(f'<c r="{col}{n}"{style} t="e"><f>{f}</f><v>#N/A</v></c>')
            if z.datum is not None:
                cells.append(f'<c r="D{n}" s="{date_style}"><v>{_excel_serial(z.datum)}</v></c>')
            if z.liter is not None:
                cells.append(self._value_cell(f"E{n}", z.liter, strings))
            if z.preis is not None:
                cells.append(self._value_cell(f"F{n}", z.preis, strings))
            if z.kilometerstand is not None:
                cells.append(self._value_cell(f"G{n}", z.kilometerstand, strings))
            if z.pruefhinweis:
                cells.append(self._value_cell(f"H{n}", z.pruefhinweis, strings))
            if n in later:
                fremd = _fremde_zellen(later.pop(n))
                if z.pruefhinweis:
                    fremd = [c for c in fremd if not c.startswith(f'<c r="H{n}"')]
                attrs = re.match(r"<row ([^>]*?)/?>", rows[n].group(0)).group(1)
                attrs = " ".join(a for a in re.findall(r'[\w:]+="[^"]*"', attrs)
                                 if a.split("=")[0] not in ("r", "spans", "hidden"))
                new_xml.append((n, f'<row r="{n}" {attrs}>' + "".join(cells + fremd) + "</row>"))
            else:
                attrs = _spans_bis_h(row_attrs)
                new_xml.append((n, f'<row r="{n}" {attrs}>' + "".join(cells) + "</row>"))
        new_xml += [(n, xml) for n, xml in later.items() if n not in removable]
        new_xml = [xml for _, xml in sorted(new_xml)]
        last = (numbers[-1] if numbers else max(start - 1, 2))

        if "</sheetData>" in sheet:
            sheet = sheet.replace("</sheetData>", "".join(new_xml) + "</sheetData>", 1)
        else:
            sheet = sheet.replace("<sheetData/>", "<sheetData>" + "".join(new_xml) + "</sheetData>", 1)
        sheet = self._pruefspalte(sheet, parts, strings)
        sheet = re.sub(r'(<dimension ref=")[^"]*(")',
                       lambda m: m.group(1) + _dimension(m.group(0), last, "H") + m.group(2), sheet, 1)
        parts[self.sheet_part] = _bereich_erweitern(sheet, liste_ende).encode("utf-8")

        table = _bereich_erweitern(parts[self.table_part].decode("utf-8"), liste_ende)
        table = _pruefspalte_in_tabelle(table)
        new_ref = f"A1:H{last}"
        table = re.sub(r'(<table\b[^>]*?\sref=")[^"]*(")', rf"\g<1>{new_ref}\g<2>", table, 1)
        table = re.sub(r'(<autoFilter\b[^>]*?\sref=")[^"]*(")', rf"\g<1>{new_ref}\g<2>", table, 1)
        parts[self.table_part] = table.encode("utf-8")

        if strings:
            parts[self.shared_part] = strings.xml()
        if self.calc_part:
            parts[self.calc_part] = _update_calc_chain(parts[self.calc_part].decode("utf-8"),
                                                       self.sheet_index, removable, numbers)
        wb = parts["xl/workbook.xml"].decode("utf-8")
        if "fullCalcOnLoad" not in wb:
            wb = re.sub(r"<calcPr\b", '<calcPr fullCalcOnLoad="1"', wb, 1)
            parts["xl/workbook.xml"] = wb.encode("utf-8")

        ziel.parent.mkdir(parents=True, exist_ok=True)
        tmp = ziel.with_name(ziel.name + ".tmp")
        try:
            with zipfile.ZipFile(tmp, "w") as z:
                for info in self.infos:
                    z.writestr(info, parts[info.filename], compress_type=info.compress_type)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        try:
            tmp.replace(ziel)
        except PermissionError:
            tmp.unlink(missing_ok=True)
            raise VorlagenFehler(f"{ziel.name} ist gesperrt (in Excel geöffnet?) – bitte schließen und erneut starten.")
        return numbers

    def _liste_erweitern(self, parts, fahrzeuge: list[Fahrzeug], strings) -> int:
        """Neue Fahrzeuge unter die letzte belegte Zeile von "Liste KfZ_Fahrer" schreiben; gibt letzte Zeile zurück."""
        xml = parts[self.liste_part].decode("utf-8")
        rows = {int(m.group(1)): m for m in ROW_RE.finditer(xml)}
        belegt = [n for n, m in rows.items() if re.search(r"<v>|<is>", m.group(0))]
        letzte = max(belegt + [1])
        muster = rows[letzte].group(0) if letzte in rows and letzte > 1 else ""
        stile = {m.group(1): (re.search(r'\ss="\d+"', m.group(3)) or [""])[0] for m in CELL_RE.finditer(muster)}
        attrs = ""
        if muster:
            attrs = " ".join(a for a in re.findall(r'[\w:]+="[^"]*"', re.match(r"<row ([^>]*?)/?>", muster).group(1))
                             if a.split("=")[0] in ("spans", "x14ac:dyDescent", "ht", "customHeight"))
        ende = letzte + len(fahrzeuge)
        for n in sorted((n for n in rows if letzte < n <= ende), reverse=True):  # leere, nur formatierte Zeilen
            xml = xml[:rows[n].start()] + xml[rows[n].end():]
        neu = []
        for i, fz in enumerate(fahrzeuge, 1):
            n = letzte + i
            zellen = [self._value_cell(f"A{n}", fz.endziffer, strings, stile.get("A", ""))]
            if fz.kennzeichen:
                zellen.append(self._value_cell(f"B{n}", fz.kennzeichen, strings, stile.get("B", "")))
            if fz.fahrer:
                zellen.append(self._value_cell(f"C{n}", fz.fahrer, strings, stile.get("C", "")))
            neu.append(f'<row r="{n}"{" " + attrs if attrs else ""}>' + "".join(zellen) + "</row>")
        danach = next((m for m in ROW_RE.finditer(xml) if int(m.group(1)) > ende), None)
        if danach:
            xml = xml[:danach.start()] + "".join(neu) + xml[danach.start():]
        elif "</sheetData>" in xml:
            xml = xml.replace("</sheetData>", "".join(neu) + "</sheetData>", 1)
        else:
            xml = xml.replace("<sheetData/>", "<sheetData>" + "".join(neu) + "</sheetData>", 1)

        def dim(m):
            z = re.search(r"([A-Z]+)(\d+)$", m.group(2))
            if not z:
                return m.group(0)
            return f'{m.group(1)}{m.group(2)[:z.start()]}{z.group(1)}{max(int(z.group(2)), ende)}"'
        xml = re.sub(r'(<dimension ref=")([^"]*)"', dim, xml, 1)
        parts[self.liste_part] = xml.encode("utf-8")
        for target in self._rels(self.liste_part).values():
            if "/tables/" in target and target in parts:
                t = parts[target].decode("utf-8")
                for tag in ("table", "autoFilter"):
                    t = re.sub(rf'(<{tag}\b[^>]*?\sref=")([^"]*)"', dim, t, 1)
                parts[target] = t.encode("utf-8")
        return ende

    def _pruefspalte(self, sheet: str, parts, strings) -> str:
        """Spalte H "Prüfhinweis" als letzte Spalte von Tabelle6: Überschrift, Breite und hellgelbe Markierung
        (bedingte Formatierung, verschwindet, sobald der Hinweis gelöscht wird)."""
        kopf = ROW_RE.search(sheet)
        if kopf and kopf.group(1) == "1" and 'r="H1"' not in kopf.group(0) and kopf.group(0).endswith("</row>"):
            g1 = next((m for m in CELL_RE.finditer(kopf.group(0)) if m.group(1) == "G"), None)
            stil = (re.search(r'\ss="\d+"', g1.group(3)) or [""])[0] if g1 else ""
            zeile = kopf.group(0)[:-len("</row>")] + self._value_cell("H1", PRUEF_TITEL, strings, stil) + "</row>"
            zeile = re.sub(r"^<row [^>]*>", lambda m: _spans_bis_h(m.group(0)), zeile)
            sheet = sheet[:kopf.start()] + zeile + sheet[kopf.end():]
        spalte = '<col min="8" max="8" width="70" customWidth="1"/>'
        cols = re.search(r"<cols>(.*?)</cols>", sheet, re.S)
        if cols is None:
            sheet = sheet.replace("<sheetData", f"<cols>{spalte}</cols><sheetData", 1)
        else:
            bereiche = [(int(a), int(b)) for a, b in re.findall(r'<col\b[^>]*?min="(\d+)"[^>]*?max="(\d+)"', cols.group(1))]
            if not any(a <= 8 <= b for a, b in bereiche):
                danach = next((m for m in re.finditer(r'<col\b[^>]*?min="(\d+)"[^>]*/>', cols.group(1))
                               if int(m.group(1)) > 8), None)
                innen = cols.group(1)
                innen = innen[:danach.start()] + spalte + innen[danach.start():] if danach else innen + spalte
                sheet = sheet[:cols.start()] + f"<cols>{innen}</cols>" + sheet[cols.end():]
        if PRUEF_FORMEL.replace('"', "&quot;") in sheet or PRUEF_FORMEL in sheet:
            return sheet
        dxf = self._gelb_dxf(parts)
        prio = max([int(p) for p in re.findall(r'<cfRule\b[^>]*?priority="(\d+)"', sheet)] + [0]) + 1
        regel = (f'<conditionalFormatting sqref="A{ERSTE_DATENZEILE}:H1048576"><cfRule type="expression" '
                 f'dxfId="{dxf}" priority="{prio}"><formula>{escape(PRUEF_FORMEL)}</formula></cfRule>'
                 "</conditionalFormatting>")
        letzte = list(re.finditer(r"</conditionalFormatting>", sheet))
        if letzte:
            pos = letzte[-1].end()
        else:
            treffer = [m.start() for t in NACH_BEDINGT for m in [re.search(rf"<{t}\b", sheet)] if m]
            pos = min(treffer) if treffer else sheet.rindex("</worksheet>")
        return sheet[:pos] + regel + sheet[pos:]

    def _gelb_dxf(self, parts) -> int:
        if not self.styles_part:
            raise VorlagenFehler("styles.xml fehlt.")
        styles = parts[self.styles_part].decode("utf-8")
        dxf = f'<dxf><fill><patternFill patternType="solid"><bgColor rgb="{PRUEF_FARBE}"/></patternFill></fill></dxf>'
        m = re.search(r'<dxfs\b[^>]*?(?:/>|>(.*?)</dxfs>)', styles, re.S)
        if m:
            vorhanden = re.findall(r"<dxf\b.*?</dxf>|<dxf/>", m.group(1) or "", re.S)
            neu = f'<dxfs count="{len(vorhanden) + 1}">' + (m.group(1) or "") + dxf + "</dxfs>"
            styles = styles[:m.start()] + neu + styles[m.end():]
            idx = len(vorhanden)
        else:
            anker = re.search(r"</cellStyles>|<cellStyles\b[^>]*/>", styles)
            pos = anker.end() if anker else styles.index("</cellXfs>") + len("</cellXfs>")
            styles = styles[:pos] + f'<dxfs count="1">{dxf}</dxfs>' + styles[pos:]
            idx = 0
        parts[self.styles_part] = styles.encode("utf-8")
        return idx

    def _zeile_ergaenzen(self, row_xml: str, n: int, z: Zeile, strings) -> str:
        zellen = {m.group(1): m for m in CELL_RE.finditer(row_xml)}
        def stil(col):
            return (re.search(r'\ss="\d+"', zellen[col].group(3)) or [""])[0] if col in zellen else ""
        neu = {"A": self._value_cell(f"A{n}", z.endziffer, strings, stil("A")),
               "H": self._value_cell(f"H{n}", z.pruefhinweis, strings, stil("H")) if z.pruefhinweis else None}
        g = zellen.get("G")
        if z.kilometerstand is not None and not (g and re.search(r"<v>|<is>", g.group(4) or "")):
            neu["G"] = self._value_cell(f"G{n}", z.kilometerstand, strings, stil("G"))
        alle = {c: m.group(0) for c, m in zellen.items()}
        for c, x in neu.items():
            if x is None:
                alle.pop(c, None)
            else:
                alle[c] = x
        kopf = _spans_bis_h(re.match(r"<row [^>]*?(?=/?>)", row_xml).group(0)) + ">"
        return kopf + "".join(alle[c] for c in sorted(alle, key=_col_nr)) + "</row>"

    def _value_cell(self, ref: str, value, strings, style: str = "") -> str:
        if isinstance(value, str):
            if strings is None:
                return f'<c r="{ref}"{style} t="inlineStr"><is><t>{escape(value)}</t></is></c>'
            return f'<c r="{ref}"{style} t="s"><v>{strings.index(value)}</v></c>'
        return f'<c r="{ref}"{style}><v>{_num(value)}</v></c>'

    def _date_style(self, parts) -> int:
        if not self.styles_part:
            raise VorlagenFehler("styles.xml fehlt.")
        styles = parts[self.styles_part].decode("utf-8")
        m = re.search(r'<cellXfs count="(\d+)">(.*?)</cellXfs>', styles, re.S)
        xfs = re.findall(r"<xf\b[^>]*?(?:/>|>.*?</xf>)", m.group(2), re.S)
        for i, xf in enumerate(xfs):
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', xf.split(">")[0]))
            if (attrs.get("numFmtId") == "14" and attrs.get("borderId", "0") == "0"
                    and attrs.get("fillId", "0") == "0" and attrs.get("fontId", "0") == "0"
                    and "<alignment" not in xf):
                return i
        new_xf = '<xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        styles = (styles[:m.start()] + f'<cellXfs count="{len(xfs) + 1}">' + m.group(2) + new_xf
                  + "</cellXfs>" + styles[m.end():])
        parts[self.styles_part] = styles.encode("utf-8")
        return len(xfs)


def _col_nr(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def _fremde_zellen(row_xml: str) -> list[str]:
    """Zellen rechts der Tabelle (ab Spalte H) – gehören nicht zu Tabelle6."""
    return [m.group(0) for m in CELL_RE.finditer(row_xml) if _col_nr(m.group(1)) > 7]


LISTE_BEREICH = re.compile(r"((?:'|&apos;)?Liste KfZ_Fahrer(?:'|&apos;)?!\$?A\$?2:\$?C\$?)(\d+)")


def _bereich_erweitern(xml: str, letzte_zeile: int) -> str:
    """SVERWEIS-Bereiche auf "Liste KfZ_Fahrer" mindestens bis letzte_zeile reichen lassen."""
    if not letzte_zeile:
        return xml
    return LISTE_BEREICH.sub(lambda m: m.group(1) + str(max(int(m.group(2)), letzte_zeile)), xml)


def _pruefspalte_in_tabelle(table: str) -> str:
    """Tabelle6 um die Spalte "Prüfhinweis" erweitern, damit Sortieren und Filtern H mitnehmen."""
    if f'name="{PRUEF_TITEL}"' in table:
        return table
    ids = [int(i) for i in re.findall(r'<tableColumn\b[^>]*?\sid="(\d+)"', table)]
    spalte = f'<tableColumn id="{max(ids + [0]) + 1}" name="{PRUEF_TITEL}"/>'
    table = re.sub(r'(<tableColumns\b[^>]*?count=")(\d+)"', lambda m: f'{m.group(1)}{int(m.group(2)) + 1}"', table, 1)
    return table.replace("</tableColumns>", spalte + "</tableColumns>", 1)


def _spans_bis_h(attrs: str) -> str:
    return re.sub(r'spans="(\d+):(\d+)"', lambda m: f'spans="{m.group(1)}:{max(int(m.group(2)), 8)}"', attrs)


def _dimension(tag: str, last_row: int, min_col: str = "G") -> str:
    m = re.search(r':([A-Z]+)(\d+)"', tag)
    col, row = (min_col, last_row) if not m else (m.group(1), int(m.group(2)))
    if _col_nr(col) < _col_nr(min_col):
        col = min_col
    return f"A1:{col}{max(row, last_row)}"


def _has_values(row_xml: str) -> bool:
    for m in CELL_RE.finditer(row_xml):
        if m.group(1) in ("A", "D", "E", "F", "G") and re.search(r"<v>|<is>", m.group(4) or ""):
            return True
    return False


class _SharedStrings:
    def __init__(self, data: bytes | None):
        self.text = data.decode("utf-8") if data else (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="0" uniqueCount="0"></sst>')
        items = re.findall(r"<si>(.*?)</si>|<si/>", self.text, re.S)
        self.lookup = {}
        for i, item in enumerate(items):
            m = re.fullmatch(r'<t(?: xml:space="preserve")?>(.*?)</t>', item or "", re.S)
            if m:
                self.lookup.setdefault(_unescape(m.group(1)), i)
        self.unique = len(items)
        self.added: list[str] = []
        self.refs = 0

    def index(self, value: str) -> int:
        self.refs += 1
        if value not in self.lookup:
            self.lookup[value] = self.unique
            self.unique += 1
            self.added.append(value)
        return self.lookup[value]

    def xml(self) -> bytes:
        text = self.text
        preserve = ' xml:space="preserve"'
        extra = "".join(f"<si><t{preserve if v != v.strip() else ''}>{escape(v)}</t></si>" for v in self.added)
        text = re.sub(r"</sst>\s*$", extra + "</sst>", text)
        count = re.search(r'\scount="(\d+)"', text)
        if count:
            text = text.replace(count.group(0), f' count="{int(count.group(1)) + self.refs}"', 1)
        text = re.sub(r'uniqueCount="\d+"', f'uniqueCount="{self.unique}"', text, 1)
        return text.encode("utf-8")


def _unescape(s: str) -> str:
    return s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&")


def _update_calc_chain(xml: str, sheet_index: int, removed_rows, new_rows) -> str:
    entries, current = [], None
    for m in re.finditer(r"<c\b([^>]*?)/>", xml):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
        current = attrs.get("i", current) or "1"
        attrs["i"] = current
        entries.append(attrs)
    removed = set(removed_rows)
    kept = [a for a in entries
            if not (a["i"] == str(sheet_index) and int(re.search(r"\d+", a["r"]).group(0)) in removed)]
    vorhanden = {(a["i"], a["r"]) for a in kept}
    for n in new_rows:
        kept += [{"r": f"{c}{n}", "i": str(sheet_index)} for c in "BC"
                 if (str(sheet_index), f"{c}{n}") not in vorhanden]
    body = "".join("<c " + " ".join(f'{k}="{v}"' for k, v in a.items()) + "/>" for a in kept)
    head = xml[:xml.index("<calcChain")]
    open_tag = re.search(r"<calcChain\b[^>]*>", xml).group(0)
    return head + open_tag + body + "</calcChain>"
