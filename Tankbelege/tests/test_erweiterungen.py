import contextlib
import json
import sys
import zipfile
from datetime import date
from pathlib import Path

import openpyxl
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import belege_core as bc  # noqa: E402
import einstellungen  # noqa: E402
import ki_anbieter  # noqa: E402
import pruef_assistent as pa  # noqa: E402
from excel_vorlage import ExcelVorlage, VorlagenFehler, Zeile  # noqa: E402
from verarbeitung import pruefe_ziel_frei, verarbeiten, zeilen_aus_beleg  # noqa: E402

VORLAGE = ROOT / "Tanken_neu - Kopie.xlsx"
FUSS = "\n20.01.2026 12:57\nKennzeichen GE EL 545E\nKilometerstand 11836\n"


@pytest.fixture(scope="module")
def fz():
    return ExcelVorlage(VORLAGE).fahrzeuge


def parse(text, fz):
    return bc.parse_text(text + FUSS, fz)


def liter(d):
    return [(z.liter, z.preis) for z in zeilen_aus_beleg(d, "q")]


@pytest.mark.parametrize("zeile,menge,einheit,preis", [
    ("CNG 14,25 kg 1,399 EUR/kg 19,94", 14.25, "kg", 19.94),
    ("Bio-CNG 9,80 kg 1,49 €/kg 14,60", 9.80, "kg", 14.60),
    ("Erdgas H-Gas 11,02 kg 16,42 EUR", 11.02, "kg", 16.42),
    ("LPG 38,40 l 0,999 €/l 38,36", 38.40, "l", 38.36),
    ("Autogas 41,00 Liter 40,96 EUR", 41.0, "l", 40.96),
])
def test_gas_ist_kraftstoff(fz, zeile, menge, einheit, preis):
    d = parse(f"{zeile}\nSumme {preis:.2f}".replace(".", ","), fz)
    assert (d.menge, d.einheit, d.kraftstoff_preis) == (menge, einheit, preis)
    assert liter(d) == [(menge, preis)]


def test_waesche_mit_tankung_zwei_zeilen(fz):
    d = parse("Diesel 40,00 l 70,00\n1,750 €/l\nWaschanlage Programm 3 14,99\nSumme 84,99", fz)
    assert liter(d) == [(40.0, 70.0), ("Wäsche", 14.99)]


def test_doppelt_gedruckte_waesche_zaehlt_einmal(fz):
    d = parse("Super 56,37 l 101,41\n1,799 €/l\nWash Glanzwäsche € 11,49\n0082 Glanzwäsche 11,49 EUR\n"
              "Summe 112,90", fz)
    assert liter(d) == [(56.37, 101.41), ("Wäsche", 11.49)] and d.rest() == 0


@pytest.mark.parametrize("waesche", ["Textilwäsche 0,00", "Glanzwäsche\n0,00 EUR", "Wäsche\nSumme 70,00"])
def test_keine_waesche_zeile_bei_0_euro(fz, waesche):
    d = parse(f"Diesel 40,00 l 70,00\n1,750 €/l\n{waesche}\nSumme 70,00", fz)
    assert liter(d) == [(40.0, 70.0)]
    assert not d.hat_waesche


def test_waesche_ohne_preis_aus_zeile_wird_nie_geschrieben(fz):
    d = bc.BelegDaten(fahrzeug=fz.keys["545E"], datum=date(2026, 1, 1), waesche_preis=0.0)
    assert zeilen_aus_beleg(d, "q") == []


@pytest.mark.parametrize("zeile,art,preis", [
    ("AdBlue 10,00 l 8,99", "AdBlue", 8.99),
    ("Innenreinigung 12,00", "Pflege", 12.0),
    ("Staubsauger 2,00", "Pflege", 2.0),
    ("Autopflege Cockpitspray 6,49", "Pflege", 6.49),
    ("Scheibenreiniger Sommer 5,99", "Wischwasser", 5.99),
    ("Wischwasser 3l 4,49", "Wischwasser", 4.49),
    ("Motoröl 5W-30 1l 14,90", "Motoröl", 14.90),
    ("Zubehör Eiskratzer 3,50", "Zubehör", 3.50),
])
def test_sonstige_posten_mit_tankung(fz, zeile, art, preis):
    d = parse(f"Diesel 40,00 l 70,00\n1,750 €/l\n{zeile}\nSumme {70 + preis:.2f}".replace(".", ","), fz)
    assert liter(d) == [(40.0, 70.0), (art, preis)]
    assert d.rest() == 0


def test_nur_pflege_ohne_tankung_wird_uebernommen(fz):
    d = parse("Innenreinigung\n15,00\nSumme 15,00", fz)
    assert not d.fehlende_pflichtfelder() and liter(d) == [("Pflege", 15.0)]


def _pdf(ordner: Path, name: str, text: str):
    import pymupdf
    ordner.mkdir(exist_ok=True)
    doc = pymupdf.open()
    doc.new_page().insert_text((40, 60), text, fontsize=9)
    doc.save(ordner / name)


def test_nicht_zugeordneter_betrag_wird_gemeldet(tmp_path):
    _pdf(tmp_path / "B", "x.pdf", "Diesel 40,00 l 70,00\n1,750 €/l\nKaffee 3,20\nSumme 73,20" + FUSS)
    erg = verarbeiten(VORLAGE, tmp_path / "B", tmp_path / "t.xlsx")
    assert [(z.liter, z.preis) for _, z in erg.zeilen] == [(40.0, 70.0)]
    assert any("x.pdf (Seite 1)" in h and "3,20 € keiner Position zugeordnet" in h for h in erg.hinweise)


def test_unbekanntes_fahrzeug_wird_angelegt(tmp_path):
    belege = tmp_path / "B"
    _pdf(belege, "neu.pdf", "Super E10 30,00 l 52,50\n1,750 €/l\n02.03.2026\nKennzeichen GE EL 4711\n"
                            "Kilometerstand 5000\nSumme 52,50")
    ziel = tmp_path / "t.xlsx"
    erg = verarbeiten(VORLAGE, belege, ziel)
    assert [(z.endziffer, z.liter) for _, z in erg.zeilen] == [(4711, 30.0)]
    liste = openpyxl.load_workbook(ziel)["Liste KfZ_Fahrer"]
    letzte = max(r for r in range(1, liste.max_row + 1) if liste.cell(r, 1).value not in (None, ""))
    assert [liste.cell(letzte, c).value for c in (1, 2, 3)] == [4711, "GE EL 4711", "Neu"]
    vorher = openpyxl.load_workbook(VORLAGE)["Liste KfZ_Fahrer"]
    assert [c.value for c in liste[letzte - 1]][:3] == [c.value for c in vorher[letzte - 1]][:3]
    ws = openpyxl.load_workbook(ziel)["Eintragungen"]
    bereich = int(ws["B3"].value.split("$C$")[1].split(",")[0])
    assert bereich >= letzte
    assert "neu angelegt" in erg.pruefung.read_text(encoding="utf-8-sig")
    assert "4711" in "\n".join(erg.zusammenfassung())

    # zweiter Lauf: Fahrzeug steht jetzt in der Liste, keine zweite Anlage, kein Duplikat
    _pdf(belege, "neu2.pdf", "Super E10 20,00 l 35,00\n1,750 €/l\n05.03.2026\nKennzeichen GE EL 4711\n"
                             "Kilometerstand 5300\nSumme 35,00")
    erg2 = verarbeiten(VORLAGE, belege, ziel)
    assert [z.liter for _, z in erg2.zeilen] == [20.0] and erg2.neue_fahrzeuge == []
    liste = openpyxl.load_workbook(ziel)["Liste KfZ_Fahrer"]
    assert [liste.cell(r, 1).value for r in range(1, liste.max_row + 1)].count(4711) == 1


def test_vlookup_bereich_wird_erweitert(tmp_path):
    import excel_vorlage as ev
    xml = "<f>VLOOKUP(A3,'Liste KfZ_Fahrer'!$A$2:$C$997,2,FALSE)</f>"
    assert "$C$1200" in ev._bereich_erweitern(xml, 1200)
    assert ev._bereich_erweitern(xml, 60) == xml


def test_ki_bekommt_seitenbild_openrouter(fz, monkeypatch):
    gesendet = {}

    def post(url, body, headers, timeout):
        gesendet.update(url=url, body=body, headers=headers)
        return {"choices": [{"message": {"content": "```json\n" + json.dumps({
            "kennzeichen": "GE EL 545E", "datum": "20.01.2026", "menge": 56.37, "einheit": "l",
            "kraftstoff_preis": 101.41, "waesche_preis": 0, "summe": 109.40,
            "posten": [{"art": "AdBlue", "preis": 7.99}, {"art": "Pflege", "preis": 0}]}) + "\n```"}}]}

    monkeypatch.setattr(ki_anbieter, "_post", post)
    ki = ki_anbieter.KiEinstellung("openrouter", "", "sk-test")
    d = ki_anbieter.frage_ki(ki, "OCR", Image.new("RGB", (40, 60), "white"), fz)
    assert gesendet["url"] == ki_anbieter.OPENROUTER_URL
    assert gesendet["body"]["model"] == "anthropic/claude-haiku-5.5"
    assert gesendet["headers"]["Authorization"] == "Bearer sk-test"
    teile = gesendet["body"]["messages"][0]["content"]
    assert teile[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert (d.fahrzeug.endziffer, d.menge, d.waesche_preis, d.posten) == ("545E", 56.37, None, (("AdBlue", 7.99),))


@pytest.mark.parametrize("anbieter,pruefe", [
    ("openai", lambda u, b, h: b["messages"][0]["content"][1]["type"] == "image_url" and "Bearer" in h["Authorization"]),
    ("gemini", lambda u, b, h: "gemini" in u and "inline_data" in b["contents"][0]["parts"][1] and h["x-goog-api-key"]),
    ("anthropic", lambda u, b, h: b["messages"][0]["content"][0]["type"] == "image" and h["x-api-key"]),
    ("ollama", lambda u, b, h: len(b["images"]) == 1 and b["format"] == "json"),
])
def test_direkte_anbieter_payload(fz, monkeypatch, anbieter, pruefe):
    antwort = json.dumps({"kennzeichen": "GE EL 545E", "menge": 10})
    formen = {"openai": {"choices": [{"message": {"content": antwort}}]},
              "gemini": {"candidates": [{"content": {"parts": [{"text": antwort}]}}]},
              "anthropic": {"content": [{"type": "text", "text": antwort}]},
              "ollama": {"response": antwort}}
    gesehen = []
    monkeypatch.setattr(ki_anbieter, "_post", lambda u, b, h, t: gesehen.append(bool(pruefe(u, b, h))) or formen[anbieter])
    ki = ki_anbieter.KiEinstellung(anbieter, "", "key", bild=True)
    d = ki_anbieter.frage_ki(ki, "OCR", Image.new("RGB", (20, 20)), fz)
    assert gesehen == [True] and d.menge == 10


def test_ki_ohne_api_key(fz):
    with pytest.raises(ValueError, match="API-Key"):
        ki_anbieter.frage_ki(ki_anbieter.KiEinstellung("openrouter"), "x", None, fz)


def test_ki_fehler_landet_im_protokoll(fz, monkeypatch):
    def kaputt(*a, **k):
        raise ValueError("HTTP 401 Unauthorized")
    monkeypatch.setattr(ki_anbieter, "_post", kaputt)
    seite = bc.BelegSeite(Path("x.pdf"), 1, text="Diesel 40,00 l\nKennzeichen GE EL 545E")
    d = bc.auswerten(seite, fz, "deu", ki_anbieter.KiEinstellung("openrouter", api_key="k"))
    assert any("HTTP 401" in h for h in d.hinweise)


def test_einstellungen_dauerhaft(tmp_path, monkeypatch):
    import tankbelege_app as app
    monkeypatch.setenv("TANKBELEGE_EINSTELLUNGEN", str(tmp_path / "e.json"))
    einstellungen.speichern({"ki_anbieter": "openrouter", "ziel": "Z.xlsx", "ki_anbieter_daten": {
        "openrouter": {"modell": "deepseek/deepseek-v4.1-flash", "api_key": einstellungen.verschluesseln("sk-1"),
                       "bild": True}}})
    assert "sk-1" not in (tmp_path / "e.json").read_text()
    anbieter, je = app.ki_aus_einstellungen(einstellungen.laden())
    ki = app.ki_einstellung(anbieter, je)
    assert (ki.anbieter, ki.modell, ki.api_key, ki.bild) == ("openrouter", "deepseek/deepseek-v4.1-flash", "sk-1", True)
    assert je["ollama"]["modell"] == bc.OLLAMA_MODEL and je["ollama"]["bild"] is False


def test_geoeffnete_zieldatei_wird_erkannt(tmp_path):
    belege = tmp_path / "B"
    _pdf(belege, "a.pdf", "Diesel 40,00 l 70,00\n1,750 €/l\nSumme 70,00" + FUSS)
    ziel = tmp_path / "t.xlsx"
    verarbeiten(VORLAGE, belege, ziel)
    vorher = ziel.read_bytes()
    (tmp_path / ".~lock.t.xlsx#").write_text("x")
    with pytest.raises(VorlagenFehler, match="geöffnet"):
        verarbeiten(VORLAGE, belege, ziel)
    assert ziel.read_bytes() == vorher and not list(tmp_path.glob("*.tmp")) and not list(tmp_path.glob("*.lock"))
    (tmp_path / ".~lock.t.xlsx#").unlink()
    pruefe_ziel_frei(ziel)


def test_fahrzeug_aus_fester_vorlage_beim_anhaengen(tmp_path):
    """Steht ein Fahrzeug nur in der festen Vorlage, nicht im alten Ziel, wird es mit Fahrer übernommen."""
    import excel_vorlage as ev
    ziel = tmp_path / "alt.xlsx"
    with zipfile.ZipFile(VORLAGE) as a, zipfile.ZipFile(ziel, "w") as b:
        for info in a.infolist():
            data = a.read(info.filename)
            if info.filename == ExcelVorlage(VORLAGE).liste_part:
                xml = data.decode()
                ws = openpyxl.load_workbook(VORLAGE)["Liste KfZ_Fahrer"]
                nr = next(r for r in range(2, ws.max_row + 1) if ws.cell(r, 1).value == 1800)
                weg = ws[nr]
                m = next(m for m in ev.ROW_RE.finditer(xml) if m.group(1) == str(nr))
                data = (xml[:m.start()] + xml[m.end():]).encode()
            b.writestr(info, data)
    endziffer, kz, fahrer = (c.value for c in weg[:3])
    belege = tmp_path / "B"
    _pdf(belege, "a.pdf", f"Diesel 40,00 l 70,00\n1,750 €/l\nSumme 70,00\n20.01.2026\nKennzeichen {kz}\nkm 100")
    erg = verarbeiten(VORLAGE, belege, ziel)
    assert [z.endziffer for _, z in erg.zeilen] == [endziffer]
    werte = [[c.value for c in r[:3]] for r in openpyxl.load_workbook(ziel)["Liste KfZ_Fahrer"].iter_rows()]
    assert [endziffer, kz, fahrer] in werte


def test_waesche_0_euro_nimmt_keinen_folgepreis(fz):
    d = parse("Super 30,00 l 52,50\n1,750 €/l\nWäsche 0,00\nKaffee 3,20\nSumme 55,70", fz)
    assert liter(d) == [(30.0, 52.5)] and d.rest() == 3.2


def test_gleich_teure_verschiedene_posten_zaehlen_beide(fz):
    d = parse("Innenreinigung 5,00\nStaubsauger 5,00\nSumme 10,00", fz)
    assert sum(p for _, p in liter(d)) == 10.0 and d.rest() == 0


def test_tankmenge_nach_zusatzartikel(fz):
    d = parse("Wischwasser 4,99\n40,00 l 70,00\nSumme 74,99", fz)
    assert sorted(liter(d), key=str) == sorted([(40.0, 70.0), ("Wischwasser", 4.99)], key=str)


def test_motoroel_diesel_ist_keine_tankung(fz):
    d = parse("Diesel 40,00 l 70,00\n1,750 €/l\nMotoröl Diesel 1,00 l 14,90\nSumme 84,90", fz)
    assert liter(d) == [(40.0, 70.0), ("Motoröl", 14.9)]


def test_neues_kennzeichen_anderer_ort(tmp_path):
    _pdf(tmp_path / "B", "n.pdf", "Super E10 30,00 l 52,50\n02.03.2026\nKennzeichen B AB 1234\n"
                                  "Kilometerstand 5000\nSumme 52,50")
    erg = verarbeiten(VORLAGE, tmp_path / "B", tmp_path / "t.xlsx")
    assert [(z.endziffer, z.liter) for _, z in erg.zeilen] == [(1234, 30.0)]


def test_ki_bekommt_bild_bei_text_pdf_und_bucht_posten_einmal(tmp_path, fz, monkeypatch):
    _pdf(tmp_path, "t.pdf", "Diesel 40,00 l\nSumme 77,99\n20.01.2026 12:57\nKennzeichen GE EL 545E\n")
    seite = next(bc.iter_belege(tmp_path))
    assert seite.text and seite.image is None
    erhalten = {}

    def frage(ki, text, bild, fahrzeuge, timeout=180):
        erhalten["bild"] = bild
        return bc.BelegDaten(kilometerstand=11836, posten=(("AdBlue", 7.99),))

    monkeypatch.setattr(ki_anbieter, "frage_ki", frage)
    d = bc.auswerten(seite, fz, "deu", ki_anbieter.KiEinstellung("openrouter", "", "k"))
    assert erhalten["bild"] is not None
    assert liter(d) == [(40.0, 70.0), ("AdBlue", 7.99)] and d.rest() == 0


def test_einstellungsdatei_nur_fuer_eigenen_benutzer(tmp_path, monkeypatch):
    import os
    import stat
    monkeypatch.setenv("TANKBELEGE_EINSTELLUNGEN", str(tmp_path / "e.json"))
    einstellungen.speichern({"a": 1})
    einstellungen.speichern({"a": 2})
    if os.name != "nt":
        assert stat.S_IMODE((tmp_path / "e.json").stat().st_mode) == 0o600
    assert einstellungen.laden() == {"a": 2}


def test_gebindegroesse_nach_zusatzartikel(fz):
    d = parse("Wischwasser 4,99\n5,00 l\nDiesel 40,00 l 70,00\nSumme 74,99", fz)
    assert sorted(liter(d), key=str) == sorted([(40.0, 70.0), ("Wischwasser", 4.99)], key=str)


def test_adblue_getrennt_geschrieben_zaehlt_einmal(fz):
    d = parse("Diesel 40,00 l 70,00\n1,750 €/l\nAdBlue 7,99\nAd Blue 7,99\nSumme 77,99", fz)
    assert liter(d) == [(40.0, 70.0), ("AdBlue", 7.99)]


def test_gelesener_kraftstoffpreis_bleibt_bei_ki_posten(tmp_path, fz, monkeypatch):
    _pdf(tmp_path, "r.pdf", "Diesel 40,00 l 70,00\n1,750 €/l\nRabatt -2,00\nSumme 75,00\n"
                            "20.01.2026 12:57\nKennzeichen GE EL 545E\n")
    seite = next(bc.iter_belege(tmp_path))
    monkeypatch.setattr(ki_anbieter, "frage_ki", lambda *a, **k: bc.BelegDaten(posten=(("AdBlue", 7.0),)))
    d = bc.auswerten(seite, fz, "deu", ki_anbieter.KiEinstellung("openrouter", "", "k"))
    assert d.kraftstoff_preis == 70.0


def test_literzahl_vor_kraftstoffzeile_nach_zusatzartikel(fz):
    d = parse("Wischwasser 4,99\n40,00 l\nDiesel 70,00\nSumme 74,99", fz)
    assert sorted(liter(d), key=str) == sorted([(40.0, 70.0), ("Wischwasser", 4.99)], key=str)


def test_zwei_motoroele_gleicher_preis(fz):
    d = parse("Öl 5W-30 12,90\nÖl 10W-40 12,90\nSumme 25,80", fz)
    assert liter(d) == [("Motoröl", 25.8)] and d.rest() == 0


def test_abgeleiteter_preis_ueberlebt_mehrheitsentscheid(fz):
    a = parse("Diesel 40,00 l\nAdBlue\nSumme 77,99", fz)
    assert a.preis_abgeleitet
    assert bc.combine([a, a]).preis_abgeleitet


def test_motoroel_schreibweisen_zaehlen_einmal(fz):
    d = parse("Öl 5W-30 12,90\nÖl 5W30 12,90\nSumme 12,90", fz)
    assert liter(d) == [("Motoröl", 12.9)]


def test_direkt_gelesener_preis_gewinnt_beim_mehrheitsentscheid(fz):
    abgeleitet = parse("Diesel 40,00 l\nSumme 70,00", fz)
    gelesen = parse("Diesel 40,00 l 70,00\nSumme 70,00", fz)
    assert abgeleitet.preis_abgeleitet and not gelesen.preis_abgeleitet
    assert not bc.combine([abgeleitet, gelesen]).preis_abgeleitet


def test_waesche_mit_bindestrich_zaehlt_einmal(fz):
    d = parse("Super 56,37 l 101,41\n1,799 €/l\nWash-Glanzwäsche 11,49\n0082 Glanzwäsche 11,49\nSumme 112,90", fz)
    assert liter(d) == [(56.37, 101.41), ("Wäsche", 11.49)]


def test_feste_vorlage_enthaelt_becke_und_boediger(fz):
    assert {(f.endziffer, f.kennzeichen, f.fahrer) for f in fz.fahrzeuge} >= {
        (1800, "GE EL 1800", "Becke"), (390, "GE EL 390", "Bödiger")}


def test_390_und_390e_sind_dasselbe_fahrzeug_fuer_duplikate(tmp_path):
    """GE EL 390 steht als 390 und 390E in der Vorlage; derselbe Beleg zählt nur einmal."""
    belege = tmp_path / "B"
    text = "Diesel 40,00 l 70,00\n1,750 €/l\nSumme 70,00\n20.01.2026\nKennzeichen GE EL {}\nkm 100"
    _pdf(belege, "a.pdf", text.format("390"))
    _pdf(belege, "b.pdf", text.format("390E"))
    erg = verarbeiten(VORLAGE, belege, tmp_path / "z.xlsx")
    assert len(erg.zeilen) == 1 and erg.duplikate == 1


def _eintragungen(ziel):
    return [r for r in openpyxl.load_workbook(ziel)["Eintragungen"].iter_rows(min_row=3, max_col=8, values_only=True)]


def test_pruefhinweis_in_spalte_h_und_gelb(tmp_path):
    belege = tmp_path / "B"
    _pdf(belege, "a.pdf", "Diesel 40,00 l 70,00\n1,750 €/l\nSumme 70,00\n20.01.2026\nKennzeichen GE EL 1800")
    ziel = tmp_path / "z.xlsx"
    erg = verarbeiten(VORLAGE, belege, ziel)
    (zeile,) = _eintragungen(ziel)
    assert zeile[0] == 1800 and zeile[4] == 40.0 and zeile[5] == 70.0 and zeile[6] is None
    assert pa._hinweis_aus_zelle(zeile[7]) == (
        "* Bitte prüfen/vervollständigen: Handschrift/km fehlt oder unleserlich (a.pdf, Seite 1)",
        "Belege_Vorschau/a_S1.png")
    ws = openpyxl.load_workbook(ziel)["Eintragungen"]
    assert ws["H1"].value == "Prüfhinweis" and ws.tables["Tabelle6"].ref == "A1:H3"
    regeln = [r for cf in ws.conditional_formatting for r in cf.rules]
    assert [r.formula for r in regeln] == [['LEFT($H3,1)="*"']]
    assert regeln[0].dxf.fill.bgColor.rgb == "FFFFF2CC"
    assert "Mit Prüfhinweis (gelb):    1 Zeilen" in erg.zusammenfassung()
    _pdf(belege, "b.pdf", "Super 30,00 l 52,50\n1,750 €/l\nSumme 52,50\n21.01.2026\nKennzeichen GE EL 1800")
    verarbeiten(VORLAGE, belege, ziel)
    ws = openpyxl.load_workbook(ziel)["Eintragungen"]
    assert len([r for cf in ws.conditional_formatting for r in cf.rules]) == 1 and ws.max_row == 4


def test_vollstaendiger_beleg_ohne_pruefhinweis(tmp_path):
    belege = tmp_path / "B"
    _pdf(belege, "a.pdf", "Diesel 40,00 l 70,00\n1,750 €/l\nSumme 70,00\n20.01.2026\nKennzeichen GE EL 1800\nKilometerstand 5000")
    ziel = tmp_path / "z.xlsx"
    verarbeiten(VORLAGE, belege, ziel)
    assert _eintragungen(ziel)[0][7] is None
    ws = openpyxl.load_workbook(ziel)["Eintragungen"]
    assert ws["H1"].value == "Prüfhinweis" and len(list(ws.conditional_formatting)) == 1
    t = ws.tables["Tabelle6"]
    assert t.ref == "A1:H3" and [c.name for c in t.tableColumns][-2:] == ["Kilometerstand", "Prüfhinweis"]
    assert ws["B3"].value.startswith("=VLOOKUP")
    verarbeiten(VORLAGE, belege, ziel)  # Zieldatei mit 8 Spalten wird weitergeführt
    t = openpyxl.load_workbook(ziel)["Eintragungen"].tables["Tabelle6"]
    assert len(t.tableColumns) == 8 and t.tableColumns[-1].id == 8


def test_fehlende_endziffer_wird_mit_hinweis_eingetragen(tmp_path):
    belege = tmp_path / "B"
    _pdf(belege, "a.pdf", "Diesel 40,00 l 70,00\n1,750 €/l\nSumme 70,00\n20.01.2026\nKilometerstand 5000")
    ziel = tmp_path / "z.xlsx"
    erg = verarbeiten(VORLAGE, belege, ziel)
    (zeile,) = _eintragungen(ziel)
    assert zeile[0] is None and zeile[3].date() == date(2026, 1, 20) and zeile[5] == 70.0
    assert "Endziffer/Kennzeichen fehlt" in zeile[7] and erg.uebersprungen == 0
    # zweiter Lauf: nicht doppelt, auch nachdem die Endziffer von Hand ergänzt wurde
    assert verarbeiten(VORLAGE, belege, ziel).zeilen == []
    wb = openpyxl.load_workbook(ziel)
    wb["Eintragungen"]["A3"] = 1800
    wb.save(ziel)
    assert verarbeiten(VORLAGE, belege, ziel).zeilen == []


def test_nur_summe_erkannt_wird_mit_hinweis_eingetragen(tmp_path):
    belege = tmp_path / "B"
    _pdf(belege, "a.pdf", "Shop\nSumme 23,40\n20.01.2026\nKennzeichen GE EL 1800")
    ziel = tmp_path / "z.xlsx"
    verarbeiten(VORLAGE, belege, ziel)
    (zeile,) = _eintragungen(ziel)
    assert zeile[0] == 1800 and zeile[4] is None and zeile[5] == 23.4
    assert "Position unklar, nur Summe erkannt" in zeile[7]


def test_ohne_datum_kein_teilabgleich_mit_anderem_tag(tmp_path):
    import verarbeitung as v
    assert not v._teil_gleich(("1800", None, "Wäsche", 11.49), ("1800", date(2026, 1, 5), "Wäsche", 11.49))
    assert v._teil_gleich(("1800", None, None, None), ("1800", None, None, None))
    assert v._teil_gleich(("", date(2026, 1, 5), "Wäsche", 11.49), ("1800", date(2026, 1, 5), "Wäsche", 11.49))


def test_ohne_datum_und_preis_kein_erneuter_eintrag(tmp_path):
    belege = tmp_path / "B"
    _pdf(belege, "a.pdf", "Diesel 40,00 l\nKennzeichen GE EL 1800\nKilometerstand 5000")
    ziel = tmp_path / "z.xlsx"
    assert len(verarbeiten(VORLAGE, belege, ziel).zeilen) == 1
    assert verarbeiten(VORLAGE, belege, ziel).zeilen == []


def test_ersatzzeile_behaelt_kilometerstand(tmp_path):
    belege = tmp_path / "B"
    _pdf(belege, "a.pdf", "Shop\nSumme 23,40\n20.01.2026\nKennzeichen GE EL 1800\nKilometerstand 5000")
    ziel = tmp_path / "z.xlsx"
    verarbeiten(VORLAGE, belege, ziel)
    assert _eintragungen(ziel)[0][6] == 5000


def test_unsichere_zusatzposition_bekommt_pruefhinweis():
    import verarbeitung as v
    d = bc.BelegDaten(datum=date(2026, 1, 20), posten=(("AdBlue", 7.99),))
    d.fahrzeug = bc.Fahrzeug("1800", "GE EL 1800", "Becke")
    d.hinweise.append("OCR unsicher bei posten: gelesen ... gewählt")
    (z,) = v._mit_pruefhinweis(d, v.zeilen_aus_beleg(d, "a.pdf | Seite 1"))
    assert z.pruefhinweis == "* Bitte prüfen/vervollständigen: Zusatzposition unsicher (a.pdf, Seite 1)"


@pytest.mark.parametrize("menge, preis, ok", [
    (56.37, 101.41, True),   # 1,799
    (40.0, 64.76, True),     # 1,619
    (30.0, 62.97, True),     # 2,099
    (20.0, 44.78, True),     # 2,239
    (10.0, 13.59, True),     # 1,359 – untere Grenze
    (10.0, 25.49, True),     # 2,549 – obere Grenze
    (10.0, 13.39, False),    # 1,339 < 1,35
    (10.0, 25.59, False),    # 2,559 > 2,55
    (40.0, 70.00, False),    # 1,750
    (40.0, 71.94, False),    # 1,7985
])
def test_literpreis_rechnerisch_bestaetigt(menge, preis, ok):
    import verarbeitung as v
    assert v.literpreis_bestaetigt(bc.BelegDaten(menge=menge, kraftstoff_preis=preis)) is ok


def test_berechneter_preis_bestaetigt_nichts():
    import verarbeitung as v
    assert not v.literpreis_bestaetigt(bc.BelegDaten(menge=40.0, kraftstoff_preis=71.96, preis_berechnet=True))


def _beleg(**kw):
    d = bc.BelegDaten(datum=date(2026, 1, 20), kilometerstand=5000, **kw)
    d.fahrzeug = bc.Fahrzeug("1800", "GE EL 1800", "Becke")
    return d


def test_plausibler_literpreis_unterdrueckt_ocr_warnung():
    import verarbeitung as v
    for preis, erwartet in [(71.96, None), (70.00, "Liter unsicher, Preis unsicher")]:
        d = _beleg(menge=40.0, kraftstoff_preis=preis)
        d.hinweise += ["OCR unsicher bei menge: ...", "OCR unsicher bei kraftstoff_preis: ...",
                       "OCR unsicher bei kilometerstand: ..."]
        (z,) = v._mit_pruefhinweis(d, v.zeilen_aus_beleg(d, "a.pdf | Seite 1"))
        gruende = z.pruefhinweis.split(": ", 1)[1]
        assert gruende.startswith(erwartet + ", " if erwartet else "Handschrift/km unsicher")


def test_shop_rest_nur_im_protokoll(tmp_path):
    _pdf(tmp_path / "B", "x.pdf", "Diesel 40,00 l 71,96\n1,799 €/l\nKaffee 3,20\nSumme 75,16" + FUSS)
    erg = verarbeiten(VORLAGE, tmp_path / "B", tmp_path / "t.xlsx")
    assert [(z.liter, z.preis, z.pruefhinweis or None) for _, z in erg.zeilen] == [(40.0, 71.96, None)]
    assert any("3,20 € Shop-/Restbetrag nicht zugeordnet" in h for h in erg.hinweise)
    assert "3,20 € Shop-/Restbetrag nicht zugeordnet" in erg.pruefung.read_text(encoding="utf-8-sig")


def test_kombibon_summe_gleich_einzelposition_kein_fehlalarm():
    import verarbeitung as v
    d = _beleg(menge=40.0, kraftstoff_preis=70.0, waesche_preis=11.49, summe=70.0)
    assert all(not z.pruefhinweis for z in v._mit_pruefhinweis(d, v.zeilen_aus_beleg(d, "a.pdf | Seite 1")))
    d = _beleg(menge=40.0, kraftstoff_preis=70.0, waesche_preis=11.49, summe=60.0)
    assert "Positionen übersteigen die Summe" in v._mit_pruefhinweis(d, v.zeilen_aus_beleg(d, "q"))[0].pruefhinweis


def _km_excel(*eintraege):
    excel = ExcelVorlage(VORLAGE)
    excel.eintrag_zeilen = [(3 + i, (e, d, 40.0, 70.0), km) for i, (e, d, km) in enumerate(eintraege)]
    return excel


@pytest.mark.parametrize("km, datum, erwartet", [
    (4000, date(2026, 1, 5), "1800"),    # nur im Korridor von 1800 (± 1.500 km), vor dessen 5000 km am 10.01.
    (6400, date(2026, 1, 25), None),     # passt zu 1800 und 545E – mehrdeutig
    (7200, date(2026, 1, 25), "545E"),
    (20000, date(2026, 1, 25), None),    # passt zu keinem
    (4000, date(2026, 1, 25), None),     # 1800 hatte am 10.01. schon 5000 km – zeitlich unplausibel
    (5500, None, None),                  # ohne Datum mehrdeutig
])
def test_endziffer_ueber_km_verlauf(km, datum, erwartet):
    import verarbeitung as v
    excel = _km_excel((1800, date(2026, 1, 10), 5000), ("545E", date(2026, 1, 10), 6000))
    d = bc.BelegDaten(datum=datum, menge=40.0, kraftstoff_preis=71.96, kilometerstand=km)
    gefunden = v._km_zuordnung(excel, [d])
    assert (str(d.fahrzeug.endziffer) if d.fahrzeug else None) == erwartet
    assert gefunden == ({id(d)} if erwartet else set())


def test_km_verlauf_aus_neuen_belegen_und_unbekanntem_fahrzeug():
    import verarbeitung as v
    excel = _km_excel()
    bekannt = _beleg(menge=40.0, kraftstoff_preis=71.96)
    neu = bc.BelegDaten(datum=date(2026, 1, 22), kilometerstand=5400, menge=30.0, kraftstoff_preis=53.97)
    neu.fahrzeug = bc.Fahrzeug("4711", "GE EL 4711", "Neu", neu=True)
    assert v._km_zuordnung(excel, [bekannt, neu]) == {id(neu)} and neu.fahrzeug is bekannt.fahrzeug


def test_km_ergaenzte_endziffer_ohne_gelb(tmp_path):
    belege = tmp_path / "B"
    _pdf(belege, "a.pdf", "Diesel 40,00 l 71,96\nSumme 71,96\n10.01.2026\nKennzeichen GE EL 1800\nKilometerstand 5000")
    _pdf(belege, "b.pdf", "Diesel 30,00 l 53,97\nSumme 53,97\n25.01.2026\nKilometerstand 5600")
    erg = verarbeiten(VORLAGE, belege, tmp_path / "z.xlsx")
    assert [(z.endziffer, z.kilometerstand, z.pruefhinweis or None) for _, z in erg.zeilen] == \
        [(1800, 5000, None), (1800, 5600, None)]
    assert any("über KM-Verlauf ergänzt" in h for h in erg.hinweise)


def test_km_ergaenzt_steht_im_pruefhinweis_wenn_markiert():
    import verarbeitung as v
    d = _beleg(menge=40.0, kraftstoff_preis=70.0)
    d.hinweise.append("OCR unsicher bei menge: ...")
    (z,) = v._mit_pruefhinweis(d, v.zeilen_aus_beleg(d, "a.pdf | Seite 1"), km_ergaenzt=True)
    assert "Liter unsicher, Endziffer über KM-Verlauf ergänzt" in z.pruefhinweis


OHNE_KZ = "Tankstelle Musterstadt, Hauptstraße 1\nDiesel 40,00 l 71,96\nSumme 71,96\n20.01.2026\n"
MIT_KZ = OHNE_KZ + "Kennzeichen GE EL 1800\nKilometerstand 5000"


@pytest.mark.parametrize("erst, dann", [(OHNE_KZ, MIT_KZ), (MIT_KZ, OHNE_KZ)])
def test_duplikat_ohne_endziffer_behaelt_vollstaendigen(tmp_path, erst, dann):
    belege = tmp_path / "B"
    _pdf(belege, "a.pdf", erst)
    _pdf(belege, "b.pdf", dann)
    erg = verarbeiten(VORLAGE, belege, tmp_path / "z.xlsx")
    assert [(z.endziffer, z.kilometerstand, z.pruefhinweis or None) for _, z in erg.zeilen] == [(1800, 5000, None)]
    assert erg.duplikate == 1


def test_gleiche_werte_verschiedene_endziffern_bleiben(tmp_path):
    belege = tmp_path / "B"
    _pdf(belege, "a.pdf", MIT_KZ)
    _pdf(belege, "b.pdf", OHNE_KZ + "Kennzeichen GE EL 545E\nKilometerstand 11836")
    erg = verarbeiten(VORLAGE, belege, tmp_path / "z.xlsx")
    assert sorted(str(z.endziffer) for _, z in erg.zeilen) == ["1800", "545E"]


def test_vorhandene_zeile_ohne_endziffer_wird_ergaenzt(tmp_path):
    belege = tmp_path / "B"
    ziel = tmp_path / "z.xlsx"
    _pdf(belege, "a.pdf", OHNE_KZ)
    verarbeiten(VORLAGE, belege, ziel)
    (zeile,) = _eintragungen(ziel)
    assert zeile[0] is None and pa._hinweis_aus_zelle(zeile[7])[0].startswith("* ")
    _pdf(belege, "b.pdf", MIT_KZ)
    erg = verarbeiten(VORLAGE, belege, ziel)
    assert erg.zeilen == [] and [n for n, _ in erg.ergaenzt] == [3]
    (zeile,) = _eintragungen(ziel)
    assert (zeile[0], zeile[4], zeile[5], zeile[6], zeile[7] or None) == (1800, 40.0, 71.96, 5000, None)
    ws = openpyxl.load_workbook(ziel)["Eintragungen"]
    assert ws["B3"].value.startswith("=VLOOKUP") and ws.tables["Tabelle6"].ref == "A1:H3"
    assert "In Zeilen ohne Endziffer ergänzt: 3" in erg.zusammenfassung()
    assert verarbeiten(VORLAGE, belege, ziel).zeilen == []


def test_bildausschnitt_und_link_in_spalte_h(tmp_path):
    belege = tmp_path / "B"
    _pdf(belege, "Scan März.pdf", OHNE_KZ)
    ziel = tmp_path / "Ziel" / "z.xlsx"
    verarbeiten(VORLAGE, belege, ziel)
    name = pa.vorschau_name(belege / "Scan März.pdf", 1)
    assert name.startswith("Scan_März_") and name.endswith("_S1.png")
    bild = ziel.parent / "Belege_Vorschau" / name
    with Image.open(bild) as im:
        assert im.width < 900 and im.height < 600  # A4 bei 200 dpi wäre 1654 x 2339, zugeschnitten auf den Text
    ws = openpyxl.load_workbook(ziel)["Eintragungen"]
    assert ws["H3"].value.startswith(f'=HYPERLINK("Belege_Vorschau/{name}","* Bitte prüfen')
    regeln = [r for cf in ws.conditional_formatting for r in cf.rules]
    assert [r.formula for r in regeln] == [['LEFT($H3,1)="*"']]
    (p,) = pa.gelbe_zeilen(ziel)
    assert p.zeile == 3 and p.vorschau == f"Belege_Vorschau/{name}" and p.quelle() == ("Scan März.pdf", 1)
    assert pa.bild_laden(p, ziel, None).size == Image.open(bild).size
    bild.unlink()  # ohne gespeichertes Bild: Seite aus dem Belege-Ordner
    assert pa.bild_laden(p, ziel, belege) is not None


def test_zuschneiden_entfernt_weissen_rand():
    im = Image.new("RGB", (1000, 1400), "white")
    im.paste((0, 0, 0), (300, 200, 600, 900))
    im.putpixel((50, 50), (0, 0, 0))  # Staubkorn
    assert pa.zuschneiden(im, rand=10).size == (320, 720)


def test_langer_pruefhinweis_als_hyperlink():
    z = Zeile(1800, date(2026, 1, 20), 40.0, 70.0, pruefhinweis="* " + 'x"y' * 120, vorschau="Belege_Vorschau/a.png")
    zelle = ExcelVorlage(VORLAGE)._pruef_cell("H3", z, None)
    text, link = pa._hinweis_aus_zelle("=" + zelle.split("<f>")[1].split("</f>")[0].replace("&amp;", "&")
                                       .replace("&quot;", '"'))
    assert (text, link) == (z.pruefhinweis, z.vorschau)


@pytest.mark.parametrize("eingabe, erwartet", [
    (("1800", "20.01.2026", "56,37", "101,41", "11836"), (1800, date(2026, 1, 20), 56.37, 101.41, 11836)),
    (("545e", "20.01.26", "Wäsche", "11,49 €", ""), ("545E", date(2026, 1, 20), "Wäsche", 11.49, None)),
    (("", "", "", "", "12.345"), (None, None, None, None, 12345)),
])
def test_werte_lesen(eingabe, erwartet):
    z = pa.werte_lesen(*eingabe)
    assert (z.endziffer, z.datum, z.liter, z.preis, z.kilometerstand) == erwartet


@pytest.mark.parametrize("eingabe", [("1", "32.01.2026", "", "", ""), ("1", "", "", "abc", ""),
                                     ("1", "", "", "", "12,5x")])
def test_werte_lesen_fehler(eingabe):
    with pytest.raises(ValueError):
        pa.werte_lesen(*eingabe)


def _gelbe_datei(tmp_path):
    belege = tmp_path / "B"
    _pdf(belege, "a.pdf", OHNE_KZ)
    _pdf(belege, "b.pdf", "Diesel 30,00 l 52,50\n1,750 €/l\nSumme 52,50\n21.01.2026\nKennzeichen GE EL 1800")
    ziel = tmp_path / "z.xlsx"
    verarbeiten(VORLAGE, belege, ziel)
    return belege, ziel


def test_pruef_assistent_speichert_zeile_und_entfernt_gelb(tmp_path):
    belege, ziel = _gelbe_datei(tmp_path)
    assert [p.zeile for p in pa.gelbe_zeilen(ziel)] == [3, 4]
    assert pa.zeile_speichern(ziel, 3, pa.werte_lesen("545E", "20.01.2026", "40,00", "71,96", "11900")) == "datei"
    zeilen = _eintragungen(ziel)
    assert (zeilen[0][0], zeilen[0][3].date(), zeilen[0][4], zeilen[0][5], zeilen[0][6], zeilen[0][7]) == \
        ("545E", date(2026, 1, 20), 40.0, 71.96, 11900, None)
    assert [p.zeile for p in pa.gelbe_zeilen(ziel)] == [4]
    ws = openpyxl.load_workbook(ziel)["Eintragungen"]
    assert ws["B3"].value.startswith("=VLOOKUP") and ws.tables["Tabelle6"].ref == "A1:H4"
    assert ws["D3"].number_format == ws["D4"].number_format
    wb = openpyxl.load_workbook(ziel, data_only=True)
    assert wb["Eintragungen"]["B3"].value == "GE EL 545E"
    pa.zeile_speichern(ziel, 4, pa.werte_lesen("1800", "21.01.2026", "30", "52,50", ""))
    assert pa.gelbe_zeilen(ziel) == [] and len(_eintragungen(ziel)) == 2
    assert verarbeiten(VORLAGE, belege, ziel).zeilen == []  # erneuter Import: nichts doppelt


def test_pruef_assistent_nutzt_geoeffnetes_excel(tmp_path, monkeypatch):
    import types
    _, ziel = _gelbe_datei(tmp_path)
    zellen, gespeichert = {}, []

    class Bereich:
        def __init__(self, ref):
            self.ref = ref

        def ClearContents(self):
            zellen[self.ref] = None

        @property
        def Value(self):
            return zellen.get(self.ref)

        @Value.setter
        def Value(self, v):
            zellen[self.ref] = v

    blatt = types.SimpleNamespace(Range=Bereich)
    mappe = types.SimpleNamespace(FullName=str(ziel.resolve()), Worksheets=lambda name: blatt,
                                  Save=lambda: gespeichert.append(1))
    client = types.ModuleType("win32com.client")
    client.GetActiveObject = lambda name: types.SimpleNamespace(Workbooks=[mappe])
    win32com = types.ModuleType("win32com")
    win32com.client = client
    pythoncom = types.ModuleType("pythoncom")
    pythoncom.CoInitialize = pythoncom.CoUninitialize = lambda: None
    monkeypatch.setitem(sys.modules, "win32com", win32com)
    monkeypatch.setitem(sys.modules, "win32com.client", client)
    monkeypatch.setitem(sys.modules, "pythoncom", pythoncom)
    vorher = ziel.read_bytes()
    assert pa.zeile_speichern(ziel, 3, pa.werte_lesen("1800", "20.01.2026", "40", "71,96", "")) == "excel"
    assert zellen["A3"] == 1800 and zellen["E3"] == 40.0 and zellen["G3"] is None and zellen["H3"] is None
    assert gespeichert == [1] and ziel.read_bytes() == vorher


def test_pruef_fenster(tmp_path):
    tk = pytest.importorskip("tkinter")
    belege, ziel = _gelbe_datei(tmp_path)
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("kein Display")
    root.withdraw()
    try:
        f = pa.PruefFenster(root, ziel, belege)
        root.update()
        assert f.win.attributes("-topmost") and f.bild is not None
        assert f.titel.get() == "Beleg 1 von 2 – Excel-Zeile 3"
        f._zoomen(1.15)
        f._drehen()
        f.felder["endziffer"].set("1800")
        f._speichern()
        assert f.titel.get() == "Beleg 2 von 2 – Excel-Zeile 4"
        f._weiter()
        assert f.titel.get().startswith("Keine gelben Belege mehr")
        assert [p.zeile for p in pa.gelbe_zeilen(ziel)] == [4]
    finally:
        root.destroy()


def test_km_zuordnung_ruecklaeufig_zwischen_neuen_belegen():
    import verarbeitung as v
    excel = ExcelVorlage(VORLAGE)
    fz = excel.endziffer_bekannt(1800)
    basis = bc.BelegDaten(fahrzeug=fz, datum=date(2026, 1, 1), kilometerstand=10000)
    a = bc.BelegDaten(datum=date(2026, 1, 3), kilometerstand=11200)
    b = bc.BelegDaten(datum=date(2026, 1, 5), kilometerstand=10900)
    assert v._km_zuordnung(excel, [basis, b, a]) == {id(a)}
    assert b.fahrzeug is None


def test_kombibelege_mit_gleicher_waesche_bleiben_getrennt(tmp_path):
    belege = tmp_path / "B"
    _pdf(belege, "a.pdf", "Tankstelle Musterstadt\nDiesel 40,00 l 71,96\nGlanzwäsche 11,49\nSumme 83,45\n20.01.2026\n")
    _pdf(belege, "b.pdf", "Tankstelle Musterstadt\nDiesel 30,00 l 53,97\nGlanzwäsche 11,49\nSumme 65,46\n20.01.2026\n"
                          "Kennzeichen GE EL 1800\nKilometerstand 5000")
    erg = verarbeiten(VORLAGE, belege, tmp_path / "z.xlsx")
    assert sorted((str(z.endziffer), str(z.liter)) for _, z in erg.zeilen) == \
        [("1800", "30.0"), ("1800", "Wäsche"), ("None", "40.0"), ("None", "Wäsche")]


def test_kombibeleg_doppelt_gescannt_wird_zusammengefuehrt(tmp_path):
    belege = tmp_path / "B"
    text = "Tankstelle Musterstadt\nDiesel 40,00 l 71,96\nGlanzwäsche 11,49\nSumme 83,45\n20.01.2026\n"
    _pdf(belege, "a.pdf", text)
    _pdf(belege, "b.pdf", text + "Kennzeichen GE EL 1800\nKilometerstand 5000")
    erg = verarbeiten(VORLAGE, belege, tmp_path / "z.xlsx")
    assert sorted((str(z.endziffer), str(z.liter)) for _, z in erg.zeilen) == [("1800", "40.0"), ("1800", "Wäsche")]


def test_neues_fahrzeug_ersetzt_zeile_ohne_endziffer(tmp_path):
    belege = tmp_path / "B"
    _pdf(belege, "a.pdf", OHNE_KZ)
    _pdf(belege, "b.pdf", OHNE_KZ + "Kennzeichen GE EL 4711\nKilometerstand 5000")
    ziel = tmp_path / "z.xlsx"
    erg = verarbeiten(VORLAGE, belege, ziel)
    assert [str(z.endziffer) for _, z in erg.zeilen] == ["4711"]
    assert [f.endziffer for f in erg.neue_fahrzeuge] == [4711]
    assert ExcelVorlage(ziel).endziffer_bekannt(4711) is not None


def test_ergaenzen_mit_abweichendem_km_bleibt_gelb(tmp_path):
    belege = tmp_path / "B"
    ziel = tmp_path / "z.xlsx"
    _pdf(belege, "a.pdf", OHNE_KZ + "Kilometerstand 4000")
    verarbeiten(VORLAGE, belege, ziel)
    _pdf(tmp_path / "B2", "b.pdf", MIT_KZ)
    erg = verarbeiten(VORLAGE, tmp_path / "B2", ziel)
    assert [n for n, _ in erg.ergaenzt] == [3]
    (zeile,) = _eintragungen(ziel)
    assert zeile[0] == 1800 and zeile[6] == 4000
    assert "Kilometerstand abweichend (Excel 4000, Beleg 5000)" in pa._hinweis_aus_zelle(zeile[7])[0]


@pytest.mark.parametrize("link", ["\\\\server\\share\\x.png", "//server/share/x.png", "C:/x.png",
                                  "Belege_Vorschau/../x.png", "../Belege_Vorschau/x.png"])
def test_vorschau_link_nur_im_vorschau_ordner(tmp_path, link):
    assert pa._vorschau_pfad(tmp_path / "z.xlsx", link) is None
    p = pa.PruefZeile(3, None, None, None, None, None, "* x (\\\\server\\a.pdf, Seite 1)", link)
    assert pa.bild_laden(p, tmp_path / "z.xlsx", tmp_path) is None


def test_vorschau_link_gueltig(tmp_path):
    assert pa._vorschau_pfad(tmp_path / "z.xlsx", "Belege_Vorschau/a_S1.png") == tmp_path / "Belege_Vorschau" / "a_S1.png"


def test_vorschau_namen_eindeutig():
    namen = {pa.vorschau_name(Path(n), 1) for n in ["Scan 01.pdf", "Scan_01.pdf", "Scan_01.jpg", "Scan_01.png"]}
    assert len(namen) == 4 and "Scan_01_S1.png" in namen
    assert pa.vorschau_name(Path("2026-03_12-38.pdf"), 14) == "2026-03_12-38_S14.png"


def test_pruef_assistent_zeile_verschoben(tmp_path):
    _, ziel = _gelbe_datei(tmp_path)
    erste, zweite = pa.gelbe_zeilen(ziel)
    vorher = ziel.read_bytes()
    with pytest.raises(VorlagenFehler, match="nicht mehr der geprüfte Beleg"):
        pa.zeile_speichern(ziel, 3, pa.werte_lesen("1800", "21.01.2026", "30", "52,50", ""), erwartet=zweite)
    assert ziel.read_bytes() == vorher
    pa.zeile_speichern(ziel, 3, pa.werte_lesen("545E", "20.01.2026", "40", "71,96", ""), erwartet=erste)
    assert [p.zeile for p in pa.gelbe_zeilen(ziel)] == [4]


def test_pruef_assistent_liest_erst_unter_der_sperre(tmp_path, monkeypatch):
    belege, ziel = _gelbe_datei(tmp_path)
    import verarbeitung as v
    echte_sperre = v._ziel_sperre

    @contextlib.contextmanager
    def sperre_mit_import(z, log):
        monkeypatch.setattr(v, "_ziel_sperre", echte_sperre)
        _pdf(tmp_path / "B3", "c.pdf", "Diesel 20,00 l 35,98\nSumme 35,98\n22.01.2026\nKennzeichen GE EL 545E\n"
                                       "Kilometerstand 12000\nTankstelle")
        verarbeiten(VORLAGE, tmp_path / "B3", ziel)  # Import endet kurz bevor der Assistent die Sperre bekommt
        with echte_sperre(z, log):
            yield
    monkeypatch.setattr(v, "_ziel_sperre", sperre_mit_import)
    erste = pa.gelbe_zeilen(ziel)[0]
    pa.zeile_speichern(ziel, 3, pa.werte_lesen("545E", "20.01.2026", "40", "71,96", ""), erwartet=erste)
    assert len(_eintragungen(ziel)) == 3


def test_korrigierter_beleg_wird_nicht_erneut_gebucht(tmp_path):
    belege, ziel = _gelbe_datei(tmp_path)
    erste, zweite = pa.gelbe_zeilen(ziel)
    pa.zeile_speichern(ziel, 3, pa.werte_lesen("545E", "20.01.2026", "40", "72,96", "11900"), erwartet=erste)
    pa.zeile_speichern(ziel, 4, pa.werte_lesen("1800", "21.01.2026", "30", "52,50", "6000"), erwartet=zweite)
    erg = verarbeiten(VORLAGE, belege, ziel)
    assert erg.zeilen == [] and erg.ergaenzt == []
    assert len(_eintragungen(ziel)) == 2
