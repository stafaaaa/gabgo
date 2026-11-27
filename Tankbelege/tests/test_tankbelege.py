import sys
import zipfile
from datetime import date
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import belege_core as bc  # noqa: E402
from excel_vorlage import ExcelVorlage, VorlagenFehler, Zeile  # noqa: E402
from verarbeitung import verarbeiten  # noqa: E402

VORLAGE = ROOT / "Tanken_neu - Kopie.xlsx"

BELEG_TEXT = """TotalEnergies Tankstelle
* 56,37 Liter * 02 *
Super € 101,41
1,799 € / Liter
Wash Glanzwäsche € 11,49
Summe € 112,90
20/01/2026 12:57:00
0094 Super E5
56,37 L 1,799 E/L
Kilometerstand 11836
KFZ-Kennzeichen GE EL 5456
"""


@pytest.fixture(scope="module")
def vorlage():
    return ExcelVorlage(VORLAGE)


@pytest.mark.parametrize("raw,expected", [
    ("Kennzeichen GE EL 5456", "545E"),
    ("KFZ-Kennzeichen GF FL 170", 170),
    ("Kfz: GE EL 545E", "545E"),
    ("KFZ-Kennzeichen GE LE 1026", "102E"),
    ("Kennzeichen GE EL 1O03", 1003),
    ("Fahrzeug GE-EL 390", "390E"),
])
def test_endziffer_ocr_toleranz(vorlage, raw, expected):
    fz, _, _ = vorlage.fahrzeuge.find_in_text(raw)
    assert fz is not None and fz.endziffer == expected


def test_unbekanntes_kennzeichen(vorlage):
    assert vorlage.fahrzeuge.find_in_text("Kennzeichen GE EL 9999")[0] is None


def test_parse_kraftstoff_und_waesche(vorlage):
    d = bc.parse_text(BELEG_TEXT, vorlage.fahrzeuge)
    assert (d.fahrzeug.endziffer, d.datum, d.menge, d.kraftstoff_preis, d.waesche_preis,
            d.kilometerstand, d.summe) == ("545E", date(2026, 1, 20), 56.37, 101.41, 11.49, 11836, 112.90)


def test_parse_kg_ohne_waesche(vorlage):
    d = bc.parse_text("Erdgas CNG 12,40 kg 1,499 EUR/kg 18,59 EUR\nDatum 03.09.26\n"
                      "Km-Stand: 45.120\nKennzeichen GE EL 170", vorlage.fahrzeuge)
    assert (d.menge, d.einheit, d.kraftstoff_preis, d.waesche_preis, d.kilometerstand, d.datum) == \
        (12.40, "kg", 18.59, None, 45120, date(2026, 9, 3))


def test_speichern_laesst_vorlage_unveraendert(vorlage, tmp_path):
    original = VORLAGE.read_bytes()
    ziel = tmp_path / "out.xlsx"
    zeilen = [Zeile("545E", date(2026, 1, 20), 56.37, 101.41, 11836),
              Zeile("545E", date(2026, 1, 20), "Wäsche", 11.49, None),
              Zeile(170, date(2026, 1, 21), 30.5, 52.1, 9000)]
    assert vorlage.speichern(ziel, zeilen) == [3, 4, 5]
    assert VORLAGE.read_bytes() == original

    wb = openpyxl.load_workbook(ziel)
    assert wb.sheetnames == ["Liste KfZ_Fahrer", "Eintragungen"]
    ws = wb["Eintragungen"]
    assert ws.tables["Tabelle6"].ref == "A1:G5"
    assert ws.max_column == 7
    row2 = [c.value for c in ws[2]]
    assert row2[0] == 0 and row2[3:] == [None] * 4
    for r in (3, 4, 5):
        assert ws.cell(r, 2).value == row2[1] and ws.cell(r, 3).value == row2[2]
    assert [ws.cell(4, c).value for c in (1, 5, 6, 7)] == ["545E", "Wäsche", 11.49, None]
    assert ws.cell(5, 1).value == 170 and ws.cell(3, 4).value.date() == date(2026, 1, 20)

    with zipfile.ZipFile(VORLAGE) as a, zipfile.ZipFile(ziel) as b:
        assert a.namelist() == b.namelist()
        changed = {n for n in a.namelist() if a.read(n) != b.read(n)}
    assert changed <= {"xl/worksheets/sheet2.xml", "xl/tables/table1.xml", "xl/sharedStrings.xml",
                       "xl/calcChain.xml", "xl/styles.xml", "xl/workbook.xml"}


def test_vorlage_nicht_ueberschreiben(vorlage):
    with pytest.raises(VorlagenFehler):
        vorlage.speichern(VORLAGE, [])


def test_textlayer_pdf_und_duplikate(tmp_path):
    import pymupdf
    belege = tmp_path / "Belege"
    belege.mkdir()
    for name in ("a.pdf", "b.pdf"):
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((40, 60), BELEG_TEXT, fontsize=9)
        doc.save(belege / name)
    ziel = tmp_path / "Tanken_test.xlsx"
    erg = verarbeiten(VORLAGE, belege, ziel)
    assert [(n, z.liter, z.preis, z.kilometerstand) for n, z in erg.zeilen] == \
        [(3, 56.37, 101.41, 11836), (4, "Wäsche", 11.49, None)]
    assert erg.duplikate == 2
    assert (tmp_path / "Tanken_test_pruefung.txt").exists()

    erg2 = verarbeiten(ziel, belege, tmp_path / "zweiter_lauf.xlsx")
    assert erg2.zeilen == [] and erg2.duplikate == 4


def test_ollama_antwort_wird_ausgewertet(vorlage, monkeypatch):
    import io
    import json

    antwort = {"kennzeichen": "GE EL 545E", "datum": "20.01.2026", "menge": "56,37", "einheit": "l",
               "kraftstoff_preis": 101.41, "waesche_preis": 11.49, "kilometerstand": "11836"}
    body = json.dumps({"response": json.dumps(antwort)}).encode()

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(bc.urllib.request, "urlopen", lambda req, timeout: Resp(body))
    d = bc.ollama_extract("...", vorlage.fahrzeuge)
    assert (d.fahrzeug.endziffer, d.datum, d.menge, d.kraftstoff_preis, d.waesche_preis, d.kilometerstand) == \
        ("545E", date(2026, 1, 20), 56.37, 101.41, 11.49, 11836)


def test_getrennter_buchstabe_im_kennzeichen(vorlage):
    fz, _, _ = vorlage.fahrzeuge.find_in_text("KFZ-Kennzeichen GE LE 102 E")
    assert fz.endziffer == "102E"
    fz, _, _ = vorlage.fahrzeuge.find_in_text("KFZ-Kennzeichen GE LE 102")
    assert fz.endziffer == 102


def test_waschwerbung_ist_keine_waesche(vorlage):
    d = bc.parse_text("Autowäsche geöffnet\nDiesel 40,00 l 70,00\n1,750 €/l\n01.02.2026\n"
                      "Summe 70,00\nKennzeichen GE EL 545E", vorlage.fahrzeuge)
    assert (d.menge, d.kraftstoff_preis, d.waesche_preis) == (40.0, 70.0, None)


def test_adblue_ist_kein_kraftstoff(vorlage):
    d = bc.parse_text("AdBlue 10,00 l 8,99\n0,899 €/l\nDiesel 40,00 l 70,00\n1,750 €/l\n"
                      "01.02.2026\nSumme 78,99\nKennzeichen GE EL 545E", vorlage.fahrzeuge)
    assert (d.menge, d.kraftstoff_preis) == (40.0, 70.0)


def test_defekter_beleg_bricht_lauf_nicht_ab(tmp_path):
    import pymupdf
    belege = tmp_path / "Belege"
    belege.mkdir()
    (belege / "a_defekt.pdf").write_bytes(b"kein pdf")
    doc = pymupdf.open()
    doc.new_page().insert_text((40, 60), BELEG_TEXT, fontsize=9)
    doc.save(belege / "b.pdf")
    erg = verarbeiten(VORLAGE, belege, tmp_path / "t.xlsx")
    assert len(erg.zeilen) == 2 and erg.uebersprungen == 1
    assert "a_defekt.pdf: Datei nicht lesbar" in (tmp_path / "t_pruefung.txt").read_text(encoding="utf-8")


def test_notiz_unterhalb_der_tabelle_bleibt(tmp_path):
    src = tmp_path / "mit_notiz.xlsx"
    with zipfile.ZipFile(VORLAGE) as zin, zipfile.ZipFile(src, "w") as zout:
        for info in zin.infolist():
            data = zin.read(info)
            if info.filename == "xl/worksheets/sheet2.xml":
                data = data.decode().replace(
                    "</sheetData>",
                    '<row r="3"><c r="J3" t="inlineStr"><is><t>Notiz A</t></is></c></row>'
                    '<row r="10"><c r="J10" t="inlineStr"><is><t>Notiz B</t></is></c></row></sheetData>').encode()
            zout.writestr(info, data)
    ziel = tmp_path / "out.xlsx"
    ExcelVorlage(src).speichern(ziel, [Zeile("545E", date(2026, 1, 20), 56.37, 101.41, 11836)])
    ws = openpyxl.load_workbook(ziel)["Eintragungen"]
    assert (ws["A3"].value, ws["J3"].value, ws["J10"].value) == ("545E", "Notiz A", "Notiz B")
    assert ws.tables["Tabelle6"].ref == "A1:G3"


def test_zapfsaeule_hinter_kennzeichen(vorlage):
    fz, _, _ = vorlage.fahrzeuge.find_in_text("KFZ-Kennzeichen GE EL 100 3")
    assert fz.endziffer == 100
