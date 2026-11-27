"""Ablauf: Belege lesen -> Zeilen bilden -> neue .xlsx + *_pruefung.txt schreiben."""
from __future__ import annotations

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


def pruefung_pfad(ziel: Path) -> Path:
    return ziel.with_name(ziel.stem + "_pruefung.txt")


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

    excel = ExcelVorlage(vorlage)
    ergebnis = Ergebnis(ziel=ziel, pruefung=pruefung_pfad(ziel))
    hinweise = ergebnis.hinweise

    tesseract = bc.configure_tesseract()
    lang = bc.tesseract_lang() if tesseract else "eng"
    if not tesseract:
        hinweise.append(f"Tesseract nicht gefunden ({bc.TESSERACT_WINDOWS}) – Bild-Scans können nicht gelesen werden.")

    gesamt = bc.count_belege(belege_ordner)
    gesehen = set(excel.vorhandene)
    neue: list[Zeile] = []
    fortschritt(0, gesamt, "Starte ...")
    for nr, seite in enumerate(bc.iter_belege(belege_ordner), 1):
        fortschritt(nr - 1, gesamt, f"Lese {seite.name}")
        ergebnis.belege += 1
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
        for z in zeilen_aus_beleg(daten, seite.name):
            if z.key() in gesehen:
                ergebnis.duplikate += 1
                hinweise.append(f"{seite.name}: Duplikat übersprungen ({_zeile_text(z)})")
                continue
            gesehen.add(z.key())
            neue.append(z)
        log(f"{seite.name}: {_kurz(daten)}")
    fortschritt(gesamt, gesamt, "Schreibe Excel ...")

    nummern = excel.speichern(ziel, neue)
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
        f"Ergebnis:     {e.ziel}",
        f"Ollama:       {'an' if ollama else 'aus'}",
        f"Belege gelesen: {e.belege}, neue Zeilen: {len(e.zeilen)}, Duplikate: {e.duplikate}, "
        f"nicht übernommen: {e.uebersprungen}",
        "",
        "Neue Zeilen (Excel-Zeile | Endziffer | Datum | Liter | Preis | Kilometerstand | Beleg):",
    ]
    lines += [f"  {n:>4} | {_zeile_text(z)} | {z.quelle}" for n, z in e.zeilen] or ["  (keine)"]
    lines += ["", "Hinweise und Fehler:"]
    lines += [f"  - {h}" for h in e.hinweise] or ["  (keine)"]
    e.pruefung.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
