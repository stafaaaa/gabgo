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
from excel_vorlage import ExcelVorlage, VorlagenFehler  # noqa: E402
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
                nr = max(r for r in range(2, ws.max_row + 1) if str(ws.cell(r, 2).value or "").startswith("GE "))
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
