# Tankbelege → Excel

Lokale Windows-Desktop-App (Python/Tkinter), die gescannte Tankbelege aus `Belege/` liest und als neue
Zeilen an `Tabelle6` im Blatt „Eintragungen“ einer Kopie der Excel-Vorlage anhängt.

## Start

* **EXE:** `Tankbelege.exe` (aus `build_exe.bat` oder dem GitHub-Actions-Artefakt *Tankbelege-Windows*)
  neben den Ordner `Belege` legen und starten.
* **Python:** `start.bat` doppelklicken – legt beim ersten Start `.venv` an und installiert die Pakete
  aus `requirements.txt` (Python 3.10+ nötig).
* **Kommandozeile:** `python tankbelege_app.py --cli --vorlage "Tanken_neu - Kopie.xlsx" --belege Belege --ziel Tanken_2026_11.xlsx [--ki openrouter --modell ... --api-key ...]`
  (ohne `--ki` gilt der in der Oberfläche gespeicherte Anbieter; Key alternativ über `TANKBELEGE_API_KEY`)

Voraussetzung für Bild-Scans: Tesseract unter `C:\Program Files\Tesseract-OCR\tesseract.exe`
(am besten mit Sprachpaket *Deutsch*; anderer Pfad über Umgebungsvariable `TESSERACT_CMD`).

Die Excel-Vorlage `Tanken_neu - Kopie.xlsx` ist fest hinterlegt und wird in der Oberfläche nicht mehr
ausgewählt. Die App nimmt zuerst die Vorlage im Programmordner (beim Setup `C:\Program Files\Tankbelege`)
und sonst die in die EXE eingebettete Kopie. Eine andere Vorlage geht nur noch per Kommandozeile mit
`--vorlage`.

## Ablauf

1. Jede PDF-Seite bzw. jedes Bild (PDF/PNG/JPG/TIF) ist ein Beleg. Text kommt aus dem PDF-Textlayer
   (PyMuPDF), sonst per Tesseract mit mehreren Bildaufbereitungen; je Feld entscheidet die Mehrheit.
2. Das Kennzeichen wird gegen „Liste KfZ_Fahrer“ abgeglichen, mit OCR-Toleranz
   (`GE EL 5456` → `545E`, `GF FL 170` → `170`, `1O03` → `1003`).
   Steht ein Fahrzeug noch nicht in der Liste, wird es am Ende von „Liste KfZ_Fahrer“ angelegt
   (Endziffer, Kennzeichen falls erkannt, Fahrer „Neu“; beim Anhängen mit Kennzeichen/Fahrer aus der festen
   Vorlage, falls es dort steht). Die SVERWEIS-Bereiche in B/C werden bei Bedarf erweitert; das
   Prüfprotokoll vermerkt die Neuanlage.
3. Jede bezahlte Position wird eine eigene Zeile `Endziffer | Datum | Liter-Spalte | Preis`:
   Kraftstoff inkl. Gas (CNG, Bio-CNG, Erdgas, LPG/Autogas) mit Menge in l oder kg und Kilometerstand,
   außerdem `Wäsche`, `AdBlue`, `Pflege` (Innenreinigung, Staubsauger, Autopflege), `Wischwasser`,
   `Motoröl` und `Zubehör` mit Bezeichnung statt Menge. Wäsche mit 0,00 € oder ohne Preis ergibt keine Zeile.
   Passt die Summe nicht zu den erfassten Positionen, steht der Restbetrag mit Seite im Prüfprotokoll.
4. Optional ergänzt eine KI fehlende oder unsichere Felder. Auswahl in der Oberfläche: Aus (nur OCR),
   Ollama (lokal), OpenRouter (Standard `anthropic/claude-haiku-5.5`), OpenAI, Gemini oder Anthropic direkt.
   Mit „Seitenbild senden“ bekommt ein Vision-Modell das Belegbild, der OCR-Text geht als Hilfe mit.
   Anbieter, Modell und API-Key werden in `%APPDATA%\Tankbelege\einstellungen.json` gespeichert,
   der Key per Windows-DPAPI an das Benutzerkonto gebunden verschlüsselt.
5. Bereits vorhandene Einträge (Endziffer, Datum, Liter, Preis) werden übersprungen.

## Excel-Regeln

Die Vorlage wird nie überschrieben. Gibt es die Ziel-Datei noch nicht, entsteht eine neue `.xlsx` aus der
Vorlage; Blätter, Spalten, Design und Zeile 2 bleiben unverändert, B/C erhalten die VLOOKUP-Formeln aus
Zeile 2, neue Zeilen beginnen ab Zeile 3. Existiert die Ziel-Datei bereits, werden neue Einträge unter der
letzten belegten Zeile angehängt; Einträge, die dort schon stehen, werden übersprungen.
Hinweise und Fehler stehen in `<Ziel>_pruefung.txt` (beim Anhängen wird das Protokoll ergänzt).
Fehlt bei einem Beleg ein Feld oder ist es unsicher gelesen (Endziffer, Datum, Liter, Preis, Kilometerstand),
wird die Zeile mit allem Erkannten trotzdem eingetragen. In der letzten Spalte H von `Tabelle6` steht dann
(„Prüfhinweis“) z. B. `* Bitte prüfen/vervollständigen: Handschrift/km unsicher (Beleg.pdf, Seite 1)`, und die
Zeile ist hellgelb markiert. Die Markierung verschwindet, sobald der Hinweis in Spalte H gelöscht wird.
Unnötige gelbe Markierungen vermeidet die App so:
- **Literpreis-Probe:** Ergibt `Preis / Liter` einen Literpreis von 1,35–2,55 € mit einer 9 an der dritten
  Nachkommastelle (z. B. 1,799), gelten Liter und Preis als bestätigt; „Liter/Preis unsicher“ entfällt.
- **KM-Verlauf:** Fehlt die Endziffer (oder ist sie unbekannt), passt der Kilometerstand aber eindeutig
  (± 1.500 km, zeitlich plausibel) zum Verlauf genau eines Fahrzeugs aus Ziel-Datei und Import, wird dessen
  Endziffer eingetragen. Das steht im Prüfprotokoll; gelb wird die Zeile nur, wenn noch etwas anderes unsicher ist.
- **Shop-Rest:** Geht der Kraftstoff rechnerisch auf, steht ein übriger Betrag (Kaffee, Snacks …) als
  „X,XX € Shop-/Restbetrag nicht zugeordnet“ nur im Prüfprotokoll. Ist die gelesene Summe nur eine Teilsumme
  der Positionen (z. B. Kraftstoff ohne Wäsche), gibt es kein „Positionen übersteigen die Summe“.
- **Duplikat ohne Endziffer:** Stimmen Datum, Liter und Preis exakt überein und fehlt bei einem Eintrag die
  Endziffer, bleibt der vollständigere: In einer vorhandenen Zeile ohne Endziffer werden Endziffer und km ergänzt
  und der Prüfhinweis entfernt, statt eine zweite Zeile anzuhängen.
**Prüfen ohne PDF-Fenster:** Zu jeder gelben Zeile speichert die App die Belegseite als zugeschnittenes Bild
(200 dpi, ohne weiße Ränder) in `Belege_Vorschau\` neben der Ziel-Datei. Der Prüfhinweis in Spalte H ist ein
Link darauf (`=HYPERLINK("Belege_Vorschau/<Datei>_S<Seite>.png"; "* Bitte prüfen …")`); ein Klick öffnet nur das
kleine Bild. Der Knopf **„Gelbe Belege prüfen“** öffnet ein schmales Fenster (immer im Vordergrund, rechts am
Bildschirmrand) mit dem Beleg (Mausrad: Zoom, Ziehen: verschieben, „Drehen“) und den Feldern Endziffer, Datum,
Liter, Preis und Kilometerstand. **„Speichern & Nächster“** schreibt die Werte in die Zeile, löscht den
Prüfhinweis (damit verschwindet die gelbe Markierung) und lädt den nächsten gelben Beleg. Ist die Ziel-Datei
dabei in Excel geöffnet, ändert die App die Zeile direkt im offenen Excel und speichert dort (Windows); sonst
schreibt sie in die Datei.
Während eines Imports liegt neben der Ziel-Datei eine Sperrdatei `<Ziel>.xlsx.lock`. Ein zweiter Import in
dieselbe Datei bricht dann mit einem Hinweis ab, statt Einträge zu überschreiben. Eine von einem abgestürzten
Import liegen gebliebene Sperre wird nach 10 Minuten ohne Lebenszeichen automatisch entfernt.
Ist die Ziel-Datei in Excel oder LibreOffice geöffnet, bricht der Import vor dem Lesen und noch einmal vor dem
Schreiben mit einem Hinweis ab; die Datei wird über eine temporäre Kopie ersetzt und nie halb geschrieben.

## Tests

`python -m pytest tests`

## Windows-Installer (Inno Setup)

`build_setup.bat` baut die App und daraus mit [Inno Setup 6](https://jrsoftware.org/isdl.php) `Output\Tankbelege-Setup.exe`
(Skript: `installer.iss`). Liegt Tesseract unter `C:\Program Files\Tesseract-OCR`, wird es inklusive Sprachdaten mitgeliefert.
Das Setup installiert nach `C:\Program Files\Tankbelege` und legt Startmenü- sowie optional eine Desktop-Verknüpfung an.
Die installierte App nutzt `Dokumente\Tankbelege` für Belege (Unterordner `Belege`) und Ergebnisse; die Vorlage bleibt
schreibgeschützt im Programmordner. GitHub Actions baut das Setup als Download `Tankbelege-Setup`.
