"""Ablauf: Belege lesen -> Zeilen bilden -> neue .xlsx + *_pruefung.txt schreiben."""
from __future__ import annotations

import os
import time
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import belege_core as bc
from excel_vorlage import WAESCHE, ExcelVorlage, VorlagenFehler, Zeile


@dataclass
class Ergebnis:
    ziel: Path
    pruefung: Path
    zeilen: list[tuple[int, Zeile]] = field(default_factory=list)
    hinweise: list[str] = field(default_factory=list)
    belege: int = 0
    duplikate: int = 0
    uebersprungen: int = 0
    angehaengt: bool = False
    seiten_je_datei: dict[Path, int] = field(default_factory=dict)

    def zaehlung(self, pdf: bool) -> tuple[int, int]:
        """(Dateien, Seiten) für PDFs bzw. Bilddateien."""
        d = [n for f, n in self.seiten_je_datei.items() if (f.suffix.lower() == ".pdf") == pdf]
        return len(d), sum(d)

    def zusammenfassung(self) -> list[str]:
        pdf, pdf_s = self.zaehlung(True)
        bild, bild_s = self.zaehlung(False)
        nummern = [n for n, _ in self.zeilen]
        bereich = f" (Excel-Zeilen {nummern[0]}–{nummern[-1]})" if len(nummern) > 1 else \
            (f" (Excel-Zeile {nummern[0]})" if nummern else "")
        def seiten(n):
            return f"{n} Seite" if n == 1 else f"{n} Seiten"
        zeilen = [f"PDF-Dateien verarbeitet:   {pdf} ({seiten(pdf_s)})"]
        if bild:
            zeilen.append(f"Bilddateien verarbeitet:   {bild} ({seiten(bild_s)})")
        return zeilen + [
            f"Seiten insgesamt:          {pdf_s + bild_s}",
            f"Neu in Ziel-Excel:         {len(nummern)} Zeilen{bereich}",
            f"Duplikate übersprungen:    {self.duplikate}",
            f"Nicht übernommen:          {self.uebersprungen}",
        ]


def pruefung_pfad(ziel: Path) -> Path:
    return ziel.with_name(ziel.stem + "_pruefung.txt")


SPERRE_VERALTET = 10 * 60  # Sekunden ohne Lebenszeichen, danach gilt eine Sperre als liegen geblieben


def sperr_pfad(ziel: Path) -> Path:
    return ziel.with_name(ziel.name + ".lock")


@contextmanager
def _ziel_sperre(ziel: Path, log):
    """Verhindert, dass zwei Importe gleichzeitig in dieselbe Ziel-Datei schreiben."""
    sperre = sperr_pfad(ziel)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(sperre, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                alter = time.time() - sperre.stat().st_mtime
            except FileNotFoundError:
                continue
            if alter < SPERRE_VERALTET:
                raise VorlagenFehler(
                    f"In {ziel.name} schreibt gerade ein anderer Import (Sperrdatei {sperre.name}). "
                    "Bitte warten, bis er fertig ist, und dann erneut starten.")
            log(f"Alte Sperrdatei {sperre.name} von einem abgebrochenen Import wird entfernt.")
            sperre.unlink(missing_ok=True)
    else:
        raise VorlagenFehler(f"Sperrdatei {sperre.name} konnte nicht angelegt werden.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(f"Import gestartet {datetime.now():%d.%m.%Y %H:%M:%S}, Prozess {os.getpid()}\n")
    try:
        yield lambda: os.utime(sperre)
    finally:
        sperre.unlink(missing_ok=True)


def zeilen_aus_beleg(daten: bc.BelegDaten, quelle: str) -> list[Zeile]:
    endziffer = daten.fahrzeug.endziffer
    zeilen = []
    if daten.hat_kraftstoff:
        zeilen.append(Zeile(endziffer, daten.datum, daten.menge, daten.kraftstoff_preis,
                            daten.kilometerstand, quelle))
    if daten.hat_waesche:
        zeilen.append(Zeile(endziffer, daten.datum, WAESCHE, daten.waesche_preis, None, quelle))
    return zeilen


def verarbeiten(vorlage: Path, belege_ordner: Path, ziel: Path, ollama: bool = False,
                fortschritt=lambda aktuell, gesamt, text: None, log=lambda msg: None) -> Ergebnis:
    vorlage, belege_ordner, ziel = Path(vorlage), Path(belege_ordner), Path(ziel)
    if ziel.suffix.lower() != ".xlsx":
        ziel = ziel.with_suffix(".xlsx")
    if ziel.resolve() == vorlage.resolve():
        raise VorlagenFehler("Ziel-Datei darf nicht die Originalvorlage sein.")
    if not belege_ordner.is_dir():
        raise VorlagenFehler(f"Belege-Ordner nicht gefunden: {belege_ordner}")

    with _ziel_sperre(ziel, log) as lebenszeichen:
        def melden(aktuell, gesamt, text):
            lebenszeichen()
            fortschritt(aktuell, gesamt, text)
        return _verarbeiten(vorlage, belege_ordner, ziel, ollama, melden, log)


def _verarbeiten(vorlage: Path, belege_ordner: Path, ziel: Path, ollama: bool,
                 fortschritt, log) -> Ergebnis:
    anhaengen = ziel.exists()
    if anhaengen:
        try:
            excel = ExcelVorlage(ziel)
        except (VorlagenFehler, KeyError, zipfile.BadZipFile) as exc:
            raise VorlagenFehler(f"Bestehende Ziel-Datei {ziel.name} passt nicht zur Vorlage: {exc}") from exc
        log(f"{ziel.name} existiert – neue Einträge werden unten angehängt.")
    else:
        excel = ExcelVorlage(vorlage)
    ergebnis = Ergebnis(ziel=ziel, pruefung=pruefung_pfad(ziel), angehaengt=anhaengen)
    hinweise = ergebnis.hinweise

    tesseract = bc.configure_tesseract()
    lang = bc.tesseract_lang() if tesseract else "eng"
    if not tesseract:
        hinweise.append(f"Tesseract nicht gefunden ({bc.TESSERACT_WINDOWS}) – Bild-Scans können nicht gelesen werden.")

    gesamt = bc.count_belege(belege_ordner)
    gesehen = set(excel.vorhandene)
    # Einträge, deren Preis in Excel ergänzt wurde, sollen ohne erkannten Preis nicht erneut erscheinen.
    nachgetragen = {k[:3] for k in excel.vorhandene if k[3] is not None}
    neue: list[Zeile] = []
    fortschritt(0, gesamt, "Starte ...")
    for nr, seite in enumerate(bc.iter_belege(belege_ordner), 1):
        fortschritt(nr - 1, gesamt, f"Lese {seite.name}")
        ergebnis.belege += 1
        ergebnis.seiten_je_datei[seite.datei] = ergebnis.seiten_je_datei.get(seite.datei, 0) + 1
        if seite.fehler:
            hinweise.append(f"{seite.name}: Datei nicht lesbar – {seite.fehler}")
            ergebnis.uebersprungen += 1
            continue
        if seite.image is not None and not tesseract:
            hinweise.append(f"{seite.name}: übersprungen – kein Textlayer und kein Tesseract.")
            ergebnis.uebersprungen += 1
            continue
        try:
            daten = bc.auswerten(seite, excel.fahrzeuge, lang, ollama, log)
        except Exception as exc:  # einzelner defekter Beleg darf den Lauf nicht abbrechen
            hinweise.append(f"{seite.name}: Fehler beim Lesen – {exc}")
            ergebnis.uebersprungen += 1
            continue
        for h in daten.hinweise:
            hinweise.append(f"{seite.name}: {h}")
        fehlt = daten.fehlende_pflichtfelder()
        if daten.fahrzeug is None or daten.datum is None or (not daten.hat_kraftstoff and not daten.hat_waesche):
            roh = f" (gelesen: '{daten.kennzeichen_roh}')" if daten.kennzeichen_roh and daten.fahrzeug is None else ""
            hinweise.append(f"{seite.name}: NICHT übernommen – fehlt: {', '.join(fehlt)}{roh}. "
                            f"Erkannt: {_kurz(daten)}")
            ergebnis.uebersprungen += 1
            continue
        if fehlt:
            hinweise.append(f"{seite.name}: übernommen, aber bitte prüfen – fehlt: {', '.join(fehlt)}")
        if daten.hat_kraftstoff and daten.kilometerstand is None:
            hinweise.append(f"{seite.name}: Kilometerstand nicht erkannt.")
        if (daten.summe is not None and daten.kraftstoff_preis is not None
                and abs(daten.summe - daten.kraftstoff_preis - (daten.waesche_preis or 0)) > 0.02):
            hinweise.append(f"{seite.name}: Summe {daten.summe:.2f} passt nicht zu Kraftstoff + Wäsche – bitte prüfen.")
        for z in zeilen_aus_beleg(daten, seite.quelle):
            if z.preis is None and z.key()[:3] in nachgetragen:
                ergebnis.duplikate += 1
                hinweise.append(f"{seite.name}: Preis nicht erkannt, gleicher Eintrag mit Preis steht schon in "
                                f"der Datei – als Duplikat übersprungen, bitte prüfen ({_zeile_text(z)})")
                continue
            if z.key() in gesehen:
                ergebnis.duplikate += 1
                hinweise.append(f"{seite.name}: Duplikat übersprungen ({_zeile_text(z)})")
                continue
            gesehen.add(z.key())
            neue.append(z)
        log(f"{seite.name}: {_kurz(daten)}")
    fortschritt(gesamt, gesamt, "Schreibe Excel ...")

    nummern = excel.speichern(ziel, neue, anhaengen=anhaengen)
    ergebnis.zeilen = list(zip(nummern, neue))
    _schreibe_pruefung(ergebnis, vorlage, belege_ordner, ollama)
    fortschritt(gesamt, gesamt, "Fertig")
    return ergebnis


def _kurz(d: bc.BelegDaten) -> str:
    teile = [f"Endziffer {d.fahrzeug.endziffer if d.fahrzeug else '?'}",
             f"Datum {d.datum.strftime('%d.%m.%Y') if d.datum else '?'}"]
    if d.menge is not None:
        teile.append(f"{d.menge:.2f} {'kg' if d.einheit == 'kg' else 'l'} / {_eur(d.kraftstoff_preis)}")
    if d.waesche_preis is not None:
        teile.append(f"Wäsche {_eur(d.waesche_preis)}")
    teile.append(f"km {d.kilometerstand if d.kilometerstand is not None else '-'}")
    return ", ".join(teile)


def _eur(v) -> str:
    return "?" if v is None else f"{v:.2f} €".replace(".", ",")


def _zeile_text(z: Zeile) -> str:
    liter = z.liter if isinstance(z.liter, str) else f"{z.liter:.2f}".replace(".", ",")
    return (f"{z.endziffer} | {z.datum.strftime('%d.%m.%Y')} | {liter} | {_eur(z.preis)} | "
            f"{z.kilometerstand if z.kilometerstand is not None else ''}")


def _schreibe_pruefung(e: Ergebnis, vorlage: Path, ordner: Path, ollama: bool):
    lines = [
        f"Prüfprotokoll Tankbelege – {datetime.now():%d.%m.%Y %H:%M}",
        f"Vorlage:      {vorlage}",
        f"Belege:       {ordner}",
        f"Ergebnis:     {e.ziel}" + ("  (an bestehende Datei angehängt)" if e.angehaengt else ""),
        f"Ollama:       {'an' if ollama else 'aus'}",
        "",
        "Zusammenfassung:",
        *[f"  {z}" for z in e.zusammenfassung()],
        "",
        "Neue Zeilen (Excel-Zeile | Endziffer | Datum | Liter | Preis | Kilometerstand | Quelle):",
    ]
    lines += [f"  {n:>4} | {_zeile_text(z)} | {z.quelle}" for n, z in e.zeilen] or ["  (keine)"]
    lines += ["", "Hinweise und Fehler:"]
    lines += [f"  - {h}" for h in e.hinweise] or ["  (keine)"]
    text = "\n".join(lines) + "\n"
    if e.angehaengt and e.pruefung.exists():
        with e.pruefung.open("a", encoding="utf-8") as f:
            f.write("\n" + "=" * 60 + "\n" + text)
    else:
        e.pruefung.write_text(text, encoding="utf-8-sig")
