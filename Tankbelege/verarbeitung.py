"""Ablauf: Belege lesen -> Zeilen bilden -> neue .xlsx + *_pruefung.txt schreiben."""
from __future__ import annotations

import os
import time
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path

import belege_core as bc
import ki_anbieter
import pruef_assistent
from excel_vorlage import SHEET_LISTE, WAESCHE, ExcelVorlage, VorlagenFehler, Zeile


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
    neue_fahrzeuge: list = field(default_factory=list)
    ergaenzt: list[tuple[int, Zeile]] = field(default_factory=list)

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
            f"Mit Prüfhinweis (gelb):    {sum(1 for _, z in self.zeilen if z.pruefhinweis)} Zeilen",
        ] + ([f"In Zeilen ohne Endziffer ergänzt: {', '.join(str(n) for n, _ in self.ergaenzt)}"]
             if self.ergaenzt else []) + ([f"Neue Fahrzeuge angelegt:   {', '.join(str(f.endziffer) for f in self.neue_fahrzeuge)}"]
             if self.neue_fahrzeuge else [])


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


def pruefe_ziel_frei(ziel: Path):
    """Bricht ab, wenn die Ziel-Datei gerade in Excel/LibreOffice geöffnet ist."""
    if not ziel.exists():
        return
    meldung = (f"{ziel.name} ist gerade in Excel (oder einem anderen Programm) geöffnet. "
               "Bitte die Datei schließen und den Import erneut starten – es wurde nichts geschrieben.")
    try:
        with open(ziel, "r+b"):
            pass
    except PermissionError:
        raise VorlagenFehler(meldung) from None
    besitzer = [ziel.with_name(".~lock." + ziel.name + "#")]  # LibreOffice
    if os.name != "nt":  # unter Windows sperrt Excel die Datei selbst, ~$-Reste nach Absturz sind harmlos
        besitzer += [ziel.with_name("~$" + ziel.name), ziel.with_name("~$" + ziel.name[2:])]
    if any(b.exists() for b in besitzer):
        raise VorlagenFehler(meldung)


def zeilen_aus_beleg(daten: bc.BelegDaten, quelle: str) -> list[Zeile]:
    endziffer = daten.fahrzeug.endziffer if daten.fahrzeug else None
    zeilen = []
    if daten.hat_kraftstoff:
        zeilen.append(Zeile(endziffer, daten.datum, daten.menge, daten.kraftstoff_preis,
                            daten.kilometerstand, quelle))
    if daten.hat_waesche:
        zeilen.append(Zeile(endziffer, daten.datum, WAESCHE, daten.waesche_preis, None, quelle))
    for art, preis in daten.posten:
        if preis and preis > 0:
            zeilen.append(Zeile(endziffer, daten.datum, art, preis, None, quelle))
    return zeilen


def verarbeiten(vorlage: Path, belege_ordner: Path, ziel: Path, ki=None,
                fortschritt=lambda aktuell, gesamt, text: None, log=lambda msg: None) -> Ergebnis:
    vorlage, belege_ordner, ziel = Path(vorlage), Path(belege_ordner), Path(ziel)
    if ziel.suffix.lower() != ".xlsx":
        ziel = ziel.with_suffix(".xlsx")
    if ziel.resolve() == vorlage.resolve():
        raise VorlagenFehler("Ziel-Datei darf nicht die Originalvorlage sein.")
    if not belege_ordner.is_dir():
        raise VorlagenFehler(f"Belege-Ordner nicht gefunden: {belege_ordner}")
    ki = ki_anbieter.KiEinstellung.aus_wert(ki)

    with _ziel_sperre(ziel, log) as lebenszeichen:
        pruefe_ziel_frei(ziel)
        def melden(aktuell, gesamt, text):
            lebenszeichen()
            fortschritt(aktuell, gesamt, text)
        return _verarbeiten(vorlage, belege_ordner, ziel, ki, melden, log)


def _verarbeiten(vorlage: Path, belege_ordner: Path, ziel: Path, ki: ki_anbieter.KiEinstellung,
                 fortschritt, log) -> Ergebnis:
    anhaengen = ziel.exists()
    if anhaengen:
        try:
            excel = ExcelVorlage(ziel)
        except (VorlagenFehler, KeyError, zipfile.BadZipFile) as exc:
            raise VorlagenFehler(f"Bestehende Ziel-Datei {ziel.name} passt nicht zur Vorlage: {exc}") from exc
        log(f"{ziel.name} existiert – neue Einträge werden unten angehängt.")
        try:  # Fahrzeuge, die nur in der (neueren) festen Vorlage stehen, mit Kennzeichen/Fahrer übernehmen
            excel.fahrzeuge.reserve = ExcelVorlage(vorlage).fahrzeuge
        except Exception:
            pass
    else:
        excel = ExcelVorlage(vorlage)
    excel.fahrzeuge.neu_erlaubt = True
    ergebnis = Ergebnis(ziel=ziel, pruefung=pruefung_pfad(ziel), angehaengt=anhaengen)
    hinweise = ergebnis.hinweise

    tesseract = bc.configure_tesseract()
    lang = bc.tesseract_lang() if tesseract else "eng"
    if not tesseract:
        hinweise.append(f"Tesseract nicht gefunden ({bc.TESSERACT_WINDOWS}) – Bild-Scans können nicht gelesen werden.")

    gesamt = bc.count_belege(belege_ordner)
    schluessel = excel.fahrzeuge.eintrag_schluessel
    gesehen = {schluessel(k) for k in excel.vorhandene}
    # Einträge, deren Preis in Excel ergänzt wurde, sollen ohne erkannten Preis nicht erneut erscheinen.
    nachgetragen = {schluessel(k)[:3] for k in excel.vorhandene if k[3] is not None}
    eintraege = [schluessel(k) for k in excel.eintraege]
    korrigiert = [schluessel(k) for k in pruef_assistent.korrekturen_laden(ziel)] if anhaengen else []
    neue: list[Zeile] = []
    ergaenzen: dict[int, Zeile] = {}
    gelesen: list[tuple] = []
    quellen: dict[str, tuple] = {}
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
            daten = bc.auswerten(seite, excel.fahrzeuge, lang, ki, log)
        except Exception as exc:  # einzelner defekter Beleg darf den Lauf nicht abbrechen
            hinweise.append(f"{seite.name}: Fehler beim Lesen – {exc}")
            ergebnis.uebersprungen += 1
            continue
        finally:
            seite.image = None  # Seitenbilder nicht bis zum Speichern im Arbeitsspeicher halten
        for h in daten.hinweise:
            hinweise.append(f"{seite.name}: {h}")
        if not _zeilen(daten, seite.quelle):
            fehlt = daten.fehlende_pflichtfelder()
            roh = f" (gelesen: '{daten.kennzeichen_roh}')" if daten.kennzeichen_roh and daten.fahrzeug is None else ""
            betrag = f" Bezahlter Betrag laut Beleg: {_eur(daten.summe)} – bitte von Hand eintragen." \
                if daten.summe else ""
            hinweise.append(f"{seite.name}: NICHT übernommen – fehlt: {', '.join(fehlt) or 'eindeutige Position'}"
                            f"{roh}. Erkannt: {_kurz(daten)}.{betrag}")
            ergebnis.uebersprungen += 1
            continue
        gelesen.append((seite, daten))
        quellen[seite.quelle] = (seite.datei, seite.seite)
        log(f"{seite.name}: {_kurz(daten)}")

    km_ergaenzt = _km_zuordnung(excel, [d for _, d in gelesen])
    for seite, daten in gelesen:
        if id(daten) in km_ergaenzt:
            hinweise.append(f"{seite.name}: Endziffer {daten.fahrzeug.endziffer} über KM-Verlauf ergänzt "
                            f"(Kilometerstand {daten.kilometerstand}).")
        zeilen = _zeilen(daten, seite.quelle)
        fehlt = daten.fehlende_pflichtfelder()
        if fehlt:
            roh = f" (gelesen: '{daten.kennzeichen_roh}')" if daten.kennzeichen_roh and daten.fahrzeug is None else ""
            hinweise.append(f"{seite.name}: übernommen mit Prüfhinweis – fehlt: {', '.join(fehlt)}{roh}")
        if daten.hat_kraftstoff and daten.kilometerstand is None:
            hinweise.append(f"{seite.name}: Kilometerstand nicht erkannt.")
        rest = daten.rest()
        if rest is not None and rest > 0.02:
            if literpreis_bestaetigt(daten):
                hinweise.append(f"{seite.name}: {_eur(rest)} Shop-/Restbetrag nicht zugeordnet "
                                f"(Kraftstoff rechnerisch bestätigt).")
            else:
                hinweise.append(f"{seite.name}: Summe {_eur(daten.summe)}, erfasst {_eur(daten.erfasst())} – "
                                f"{_eur(rest)} keiner Position zugeordnet, bitte prüfen.")
        elif rest is not None and rest < -0.02:
            if _summe_ist_teilsumme(daten):
                hinweise.append(f"{seite.name}: gelesene Summe {_eur(daten.summe)} ist eine Teilsumme der "
                                f"Positionen ({_eur(daten.erfasst())}) – keine Abweichung.")
            else:
                hinweise.append(f"{seite.name}: erfasste Positionen ({_eur(daten.erfasst())}) übersteigen die Summe "
                                f"{_eur(daten.summe)} – bitte prüfen.")
        neu_angelegt = daten.fahrzeug is not None and daten.fahrzeug.neu and daten.fahrzeug not in ergebnis.neue_fahrzeuge
        uebernommen = False
        pz = _mit_pruefhinweis(daten, zeilen, id(daten) in km_ergaenzt)
        ziele = {}
        for z in pz:
            if _unvollstaendig(z):
                continue
            n = next((n for n, k, _ in excel.eintrag_zeilen
                      if n not in ergaenzen and _ohne_endziffer_gleich(k, z.key())), None)
            i = None if n is not None else \
                next((i for i, alt in enumerate(neue) if _ohne_endziffer_gleich(alt.key(), z.key())), None)
            if n is not None or i is not None:
                ziele[id(z)] = (n, i)
        offen = [z for z in pz if not _unvollstaendig(z) and schluessel(z.key()) not in gesehen
                 and not _korrigiert(schluessel(z.key()), korrigiert)]  # schon vorhandene Positionen zählen als Treffer
        if any(id(z) not in ziele for z in offen):
            ziele = {}  # derselbe Beleg nur, wenn alle Positionen übereinstimmen (z. B. nicht nur die Wäsche)
        for z in pz:
            if _korrigiert(schluessel(z.key()), korrigiert):
                ergebnis.duplikate += 1
                hinweise.append(f"{seite.name}: im Prüf-Assistenten schon korrigiert – übersprungen ({_zeile_text(z)})")
                continue
            if _unvollstaendig(z) and any(_teil_gleich(schluessel(z.key()), k) for k in eintraege):
                ergebnis.duplikate += 1
                hinweise.append(f"{seite.name}: unvollständiger Eintrag steht schon in der Datei – "
                                f"übersprungen ({_zeile_text(z)})")
                continue
            if z.preis is None and schluessel(z.key())[:3] in nachgetragen:
                ergebnis.duplikate += 1
                hinweise.append(f"{seite.name}: Preis nicht erkannt, gleicher Eintrag mit Preis steht schon in "
                                f"der Datei – als Duplikat übersprungen, bitte prüfen ({_zeile_text(z)})")
                continue
            if schluessel(z.key()) in gesehen:
                ergebnis.duplikate += 1
                hinweise.append(f"{seite.name}: Duplikat übersprungen ({_zeile_text(z)})")
                continue
            gesehen.add(schluessel(z.key()))
            eintraege.append(schluessel(z.key()))
            uebernommen = True
            n, i = ziele.get(id(z), (None, None))
            if n is not None:
                km_alt = next((km for m, _, km in excel.eintrag_zeilen if m == n), None)
                if km_alt is not None and z.kilometerstand is not None and km_alt != z.kilometerstand:
                    grund = f"Kilometerstand abweichend (Excel {km_alt}, Beleg {z.kilometerstand})"
                    ref = f" ({z.quelle.replace(' | ', ', ')})"
                    z = replace(z, pruefhinweis=z.pruefhinweis.replace(ref, f", {grund}{ref}") if z.pruefhinweis
                                else f"* Bitte prüfen/vervollständigen: {grund}{ref}")
                    hinweise.append(f"{seite.name}: Excel-Zeile {n}: {grund}.")
                ergaenzen[n] = z
                ergebnis.ergaenzt.append((n, z))
                hinweise.append(f"{seite.name}: Excel-Zeile {n} ohne Endziffer ist derselbe Beleg – "
                                f"Endziffer {z.endziffer} dort ergänzt statt doppelt eingetragen.")
                continue
            if i is not None:
                hinweise.append(f"{seite.name}: gleicher Beleg ohne Endziffer ({neue[i].quelle}) "
                                f"durch diesen vollständigeren ersetzt.")
                ergebnis.duplikate += 1
                neue[i] = z if z.kilometerstand is not None else replace(z, kilometerstand=neue[i].kilometerstand)
                continue
            neue.append(z)
        if neu_angelegt and uebernommen:
            fz = daten.fahrzeug
            ergebnis.neue_fahrzeuge.append(fz)
            hinweise.append(f"{seite.name}: Fahrzeug {fz.endziffer} ({fz.kennzeichen or 'Kennzeichen unbekannt'}) "
                            f"stand nicht in '{SHEET_LISTE}' – neu angelegt, Fahrer: {fz.fahrer or 'leer'}.")
    fortschritt(gesamt, gesamt, "Schreibe Excel ...")
    vorschau: dict[str, str] = {}

    def mit_vorschau(z: Zeile) -> Zeile:
        if not z.pruefhinweis or z.quelle not in quellen:
            return z
        if z.quelle not in vorschau:
            try:
                vorschau[z.quelle] = pruef_assistent.vorschau_speichern(ziel, *quellen[z.quelle])
            except Exception as exc:
                vorschau[z.quelle] = ""
                hinweise.append(f"Bildausschnitt für {z.quelle} nicht erstellt: {exc}")
        return replace(z, vorschau=vorschau[z.quelle])
    neue = [mit_vorschau(z) for z in neue]
    ergaenzen = {n: mit_vorschau(z) for n, z in ergaenzen.items()}
    ergebnis.ergaenzt = list(ergaenzen.items())

    pruefe_ziel_frei(ziel)
    nummern = excel.speichern(ziel, neue, anhaengen=anhaengen, neue_fahrzeuge=ergebnis.neue_fahrzeuge,
                              ergaenzen=ergaenzen)
    ergebnis.zeilen = list(zip(nummern, neue))
    _schreibe_pruefung(ergebnis, vorlage, belege_ordner, ki)
    fortschritt(gesamt, gesamt, "Fertig")
    return ergebnis


def _zeilen(daten: bc.BelegDaten, quelle: str) -> list[Zeile]:
    """Zeilen eines Belegs; ist keine Position erkennbar, eine Ersatzzeile mit der Belegsumme."""
    zeilen = zeilen_aus_beleg(daten, quelle)
    if not zeilen and (daten.fahrzeug is not None or daten.summe):
        zeilen = [Zeile(daten.fahrzeug.endziffer if daten.fahrzeug else None, daten.datum, None,
                        daten.summe, daten.kilometerstand, quelle)]
    return zeilen


def literpreis_bestaetigt(daten: bc.BelegDaten) -> bool:
    """Liter und Preis passen rechnerisch zu einem typischen Literpreis 1,35–2,55 € mit 9 als dritter Nachkommastelle
    (z. B. 1,799). Ein aus Liter x Literpreis berechneter Preis bestätigt nichts."""
    liter, preis = daten.menge, daten.kraftstoff_preis
    if not liter or not preis or liter <= 0 or daten.preis_berechnet:
        return False
    basis = int(preis / liter * 100)
    for cent in (basis - 1, basis, basis + 1):
        lp = (cent * 10 + 9) / 1000
        if 1.35 <= lp <= 2.55 and abs(round(liter * lp, 2) - preis) <= 0.006:
            return True
    return False


def _summe_ist_teilsumme(daten: bc.BelegDaten) -> bool:
    """Gelesene Summe entspricht einer Teilmenge der Positionen (z. B. nur Kraftstoff) – kein Fehlbetrag."""
    betraege = [b for b in [daten.kraftstoff_preis, daten.waesche_preis if daten.hat_waesche else None]
                + [p for _, p in daten.posten] if b]
    if daten.summe is None or len(betraege) < 2:
        return False
    return any(abs(sum(b for i, b in enumerate(betraege) if maske >> i & 1) - daten.summe) <= 0.01
               for maske in range(1, 2 ** len(betraege) - 1))


KM_TOLERANZ = 1500


def _ohne_endziffer(endziffer) -> bool:
    return endziffer in (None, "", 0, "0")


def _korrigiert(k: tuple, korrigiert: list[tuple]) -> bool:
    """Exakt dieselben Werte wie die ursprünglich gelesene, im Prüf-Assistenten korrigierte Zeile."""
    return k in korrigiert


def _ohne_endziffer_gleich(alt: tuple, neu: tuple) -> bool:
    """alt hat keine Endziffer, stimmt aber in Datum, Liter und Preis exakt mit neu überein."""
    return _ohne_endziffer(alt[0]) and alt[1] is not None and alt[2] is not None and alt[1:] == neu[1:]


def _km_zuordnung(excel: ExcelVorlage, belege: list[bc.BelegDaten]) -> set[int]:
    """Belege ohne (bekannte) Endziffer, deren Kilometerstand eindeutig in den KM-Verlauf genau eines
    Fahrzeugs passt, diesem Fahrzeug zuordnen. Gibt die ids der zugeordneten Belege zurück."""
    def bekannt(fz):
        return fz is not None and not _ohne_endziffer(fz.endziffer) and not (fz.neu and fz.fahrer == "Neu")
    verlauf: dict[str, list] = {}
    fahrzeug: dict[str, bc.Fahrzeug] = {}
    def merken(fz, datum, km, sicher=True):
        k = excel.fahrzeuge.eintrag_schluessel((fz.endziffer,))[0]
        fahrzeug.setdefault(k, fz)
        verlauf.setdefault(k, []).append((datum, km, sicher))
    for _, key, km in excel.eintrag_zeilen:
        fz = None if _ohne_endziffer(key[0]) else excel.endziffer_bekannt(key[0])
        if km is not None and bekannt(fz):
            merken(fz, key[1], km)
    for d in belege:
        if d.kilometerstand is not None and bekannt(d.fahrzeug):
            merken(d.fahrzeug, d.datum, d.kilometerstand)

    def passt(punkte, datum, km):
        kms = [k for _, k, sicher in punkte if sicher]  # nur bestätigte Punkte bilden den Korridor
        if not min(kms) - KM_TOLERANZ <= km <= max(kms) + KM_TOLERANZ:
            return False
        return datum is None or all(not (d and ((d < datum and k > km) or (d > datum and k < km)))
                                    for d, k, _ in punkte)
    zugeordnet = set()
    offen = [d for d in belege if d.kilometerstand is not None and not bekannt(d.fahrzeug)]
    for d in sorted(offen, key=lambda d: (d.datum is None, d.datum or date.min)):
        treffer = [k for k, punkte in verlauf.items() if passt(punkte, d.datum, d.kilometerstand)]
        if len(treffer) == 1:
            d.fahrzeug = fahrzeug[treffer[0]]
            zugeordnet.add(id(d))
            merken(d.fahrzeug, d.datum, d.kilometerstand, sicher=False)  # folgende Belege müssen zeitlich dazu passen
    return zugeordnet


def _unvollstaendig(z: Zeile) -> bool:
    return z.endziffer in (None, "") or z.datum is None or z.liter is None


def _teil_gleich(neu: tuple, alt: tuple) -> bool:
    """Unvollständiger Eintrag gilt als vorhanden, wenn ein Eintrag in allen erkannten Feldern übereinstimmt
    (z. B. nachdem die fehlende Endziffer von Hand ergänzt wurde). Ohne Datum zählt nur ein gleicher
    unvollständiger Eintrag, sonst würden gleich teure Belege anderer Tage verschluckt."""
    if neu[1] is None:
        return neu == alt
    return all(n in (None, "") or n == a for n, a in zip(neu, alt))


def _mit_pruefhinweis(daten: bc.BelegDaten, zeilen: list[Zeile], km_ergaenzt: bool = False) -> list[Zeile]:
    """Spalte H: fehlende oder unsicher gelesene Felder je Zeile, mit Verweis auf Datei und Seite."""
    unsicher = {h.split(":")[0].removeprefix("OCR unsicher bei ").strip()
                for h in daten.hinweise if h.startswith("OCR unsicher bei ")}
    beleg = []
    if daten.fahrzeug is None:
        beleg.append("Endziffer/Kennzeichen fehlt")
    elif not km_ergaenzt and ("fahrzeug" in unsicher or any(h.startswith(("unsichere Zuordnung", "unsicher: Kennzeichen"))
                                       for h in daten.hinweise)):
        beleg.append("Endziffer unsicher")
    if daten.datum is None:
        beleg.append("Datum fehlt")
    elif "datum" in unsicher:
        beleg.append("Datum unsicher")
    rest = daten.rest()
    if rest is not None and abs(rest) <= 0.02:  # Summe bestätigt die gewählten Beträge
        unsicher -= {"kraftstoff_preis", "waesche_preis"}
    bestaetigt = literpreis_bestaetigt(daten)
    if bestaetigt:
        unsicher -= {"menge", "kraftstoff_preis"}
    if rest is not None and ((rest > 0.02 and bestaetigt) or (rest < -0.02 and _summe_ist_teilsumme(daten))):
        rest = None  # Shop-Rest bzw. Teilsumme: nur im Prüfprotokoll
    aus = []
    for i, z in enumerate(zeilen):
        gruende = list(beleg)
        if z.liter is None:
            gruende.append("Position unklar, nur Summe erkannt" if z.preis else "Position und Betrag fehlen")
        elif not isinstance(z.liter, str):
            if "menge" in unsicher:
                gruende.append("Liter unsicher")
            if z.preis is None:
                gruende.append("Preis fehlt")
            elif "kraftstoff_preis" in unsicher:
                gruende.append("Preis unsicher")
            if z.kilometerstand is None:
                gruende.append("Handschrift/km fehlt oder unleserlich")
            elif "kilometerstand" in unsicher:
                gruende.append("Handschrift/km unsicher")
        elif z.liter == WAESCHE and "waesche_preis" in unsicher:
            gruende.append("Preis unsicher")
        elif z.liter != WAESCHE and "posten" in unsicher:
            gruende.append("Zusatzposition unsicher")
        if i == 0 and z.liter is not None and rest is not None and abs(rest) > 0.02:
            gruende.append(f"{_eur(rest)} keiner Position zugeordnet" if rest > 0
                           else "Positionen übersteigen die Summe")
        if gruende and km_ergaenzt:
            gruende.append("Endziffer über KM-Verlauf ergänzt")
        if gruende:
            ref = z.quelle.replace(" | ", ", ")
            z = replace(z, pruefhinweis=f"* Bitte prüfen/vervollständigen: {', '.join(gruende)} ({ref})")
        aus.append(z)
    return aus


def _kurz(d: bc.BelegDaten) -> str:
    teile = [f"Endziffer {d.fahrzeug.endziffer if d.fahrzeug else '?'}",
             f"Datum {d.datum.strftime('%d.%m.%Y') if d.datum else '?'}"]
    if d.menge is not None:
        teile.append(f"{d.menge:.2f} {'kg' if d.einheit == 'kg' else 'l'} / {_eur(d.kraftstoff_preis)}")
    if d.hat_waesche:
        teile.append(f"Wäsche {_eur(d.waesche_preis)}")
    teile += [f"{art} {_eur(preis)}" for art, preis in d.posten]
    if d.summe is not None:
        teile.append(f"Summe {_eur(d.summe)}")
    teile.append(f"km {d.kilometerstand if d.kilometerstand is not None else '-'}")
    return ", ".join(teile)


def _eur(v) -> str:
    return "?" if v is None else f"{v:.2f} €".replace(".", ",")


def _zeile_text(z: Zeile, hinweis: bool = False) -> str:
    liter = "?" if z.liter is None else z.liter if isinstance(z.liter, str) else f"{z.liter:.2f}".replace(".", ",")
    text = (f"{'?' if z.endziffer in (None, '') else z.endziffer} | "
            f"{z.datum.strftime('%d.%m.%Y') if z.datum else '?'} | {liter} | {_eur(z.preis)} | "
            f"{z.kilometerstand if z.kilometerstand is not None else ''}")
    return text + (f" | {z.pruefhinweis}" if hinweis and z.pruefhinweis else "")


def _schreibe_pruefung(e: Ergebnis, vorlage: Path, ordner: Path, ki: ki_anbieter.KiEinstellung):
    lines = [
        f"Prüfprotokoll Tankbelege – {datetime.now():%d.%m.%Y %H:%M}",
        f"Vorlage:      {vorlage}",
        f"Belege:       {ordner}",
        f"Ergebnis:     {e.ziel}" + ("  (an bestehende Datei angehängt)" if e.angehaengt else ""),
        f"KI:           {ki.beschreibung()}",
        "",
        "Zusammenfassung:",
        *[f"  {z}" for z in e.zusammenfassung()],
        "",
        "Neue Zeilen (Excel-Zeile | Endziffer | Datum | Liter | Preis | Kilometerstand | Quelle):",
    ]
    lines += [f"  {n:>4} | {_zeile_text(z)} | {z.quelle}" + (f" | {z.pruefhinweis}" if z.pruefhinweis else "")
              for n, z in e.zeilen] or ["  (keine)"]
    lines += ["", "Hinweise und Fehler:"]
    lines += [f"  - {h}" for h in e.hinweise] or ["  (keine)"]
    text = "\n".join(lines) + "\n"
    if e.angehaengt and e.pruefung.exists():
        with e.pruefung.open("a", encoding="utf-8") as f:
            f.write("\n" + "=" * 60 + "\n" + text)
    else:
        e.pruefung.write_text(text, encoding="utf-8-sig")
