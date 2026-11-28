# Tankbelege → Excel

Lokale Windows-Desktop-App (Python/Tkinter), die gescannte Tankbelege aus `Belege/` liest und als neue
Zeilen an `Tabelle6` im Blatt „Eintragungen“ einer Kopie der Excel-Vorlage anhängt.

## Start

* **EXE:** `Tankbelege.exe` (aus `build_exe.bat` oder dem GitHub-Actions-Artefakt *Tankbelege-Windows*)
  neben die Vorlage und den Ordner `Belege` legen und starten.
* **Python:** `start.bat` doppelklicken – legt beim ersten Start `.venv` an und installiert die Pakete
  aus `requirements.txt` (Python 3.10+ nötig).
* **Kommandozeile:** `python tankbelege_app.py --cli --vorlage "Tanken_neu - Kopie.xlsx" --belege Belege --ziel Tanken_2026_11.xlsx [--ollama]`

Voraussetzung für Bild-Scans: Tesseract unter `C:\Program Files\Tesseract-OCR\tesseract.exe`
(am besten mit Sprachpaket *Deutsch*; anderer Pfad über Umgebungsvariable `TESSERACT_CMD`).

## Ablauf

1. Jede PDF-Seite bzw. jedes Bild (PDF/PNG/JPG/TIF) ist ein Beleg. Text kommt aus dem PDF-Textlayer
   (PyMuPDF), sonst per Tesseract mit mehreren Bildaufbereitungen; je Feld entscheidet die Mehrheit.
2. Das Kennzeichen wird gegen „Liste KfZ_Fahrer“ abgeglichen, mit OCR-Toleranz
   (`GE EL 5456` → `545E`, `GF FL 170` → `170`, `1O03` → `1003`).
3. Kraftstoff (Liter/kg) **und** Wäsche auf einem Beleg ergeben zwei Zeilen:
   `Endziffer | Datum | Liter | Kraftstoffpreis | km` und `Endziffer | Datum | Wäsche | Waschpreis | (leer)`.
4. Optional ergänzt ein lokales Ollama (`llama3.2:latest`) fehlende oder unsichere Felder.
5. Bereits vorhandene Einträge (Endziffer, Datum, Liter, Preis) werden übersprungen.

## Excel-Regeln

Die Vorlage wird nie überschrieben. Gibt es die Ziel-Datei noch nicht, entsteht eine neue `.xlsx` aus der
Vorlage; Blätter, Spalten, Design und Zeile 2 bleiben unverändert, B/C erhalten die VLOOKUP-Formeln aus
Zeile 2, neue Zeilen beginnen ab Zeile 3. Existiert die Ziel-Datei bereits, werden neue Einträge unter der
letzten belegten Zeile angehängt; Einträge, die dort schon stehen, werden übersprungen.
Hinweise und Fehler stehen ausschließlich in `<Ziel>_pruefung.txt` (beim Anhängen wird das Protokoll ergänzt).
Während eines Imports liegt neben der Ziel-Datei eine Sperrdatei `<Ziel>.xlsx.lock`. Ein zweiter Import in
dieselbe Datei bricht dann mit einem Hinweis ab, statt Einträge zu überschreiben. Eine von einem abgestürzten
Import liegen gebliebene Sperre wird nach 10 Minuten ohne Lebenszeichen automatisch entfernt.

## Tests

`python -m pytest tests`

## Windows-Installer (Inno Setup)

`build_setup.bat` baut die App und daraus mit [Inno Setup 6](https://jrsoftware.org/isdl.php) `Output\Tankbelege-Setup.exe`
(Skript: `installer.iss`). Liegt Tesseract unter `C:\Program Files\Tesseract-OCR`, wird es inklusive Sprachdaten mitgeliefert.
Das Setup installiert nach `C:\Program Files\Tankbelege` und legt Startmenü- sowie optional eine Desktop-Verknüpfung an.
Die installierte App nutzt `Dokumente\Tankbelege` für Belege (Unterordner `Belege`) und Ergebnisse; die Vorlage bleibt
schreibgeschützt im Programmordner. GitHub Actions baut das Setup als Download `Tankbelege-Setup`.
