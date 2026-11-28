"""Tankbelege -> Excel: grafische Oberfläche (Tkinter) und Kommandozeile."""
from __future__ import annotations

import argparse
import os
import queue
import sys
import tempfile
import threading
import traceback
from datetime import date
from pathlib import Path
from tkinter import BooleanVar, PhotoImage, StringVar, Tk, filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import einstellungen
from excel_vorlage import VorlagenFehler
from ki_anbieter import ANBIETER, KiEinstellung
from pruef_assistent import PruefFenster, gelbe_zeilen
from verarbeitung import verarbeiten, _zeile_text

APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
VORLAGE_NAME = "Tanken_neu - Kopie.xlsx"
# PyInstaller bettet die Vorlage ein (--add-data); im Skriptbetrieb liegt sie neben dem Programm.
EINGEBETTET_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))


def finde_vorlage(app_dir: Path = APP_DIR, eingebettet: Path = EINGEBETTET_DIR) -> Path | None:
    """Fest hinterlegte Vorlage: zuerst im Programmordner, sonst die in die EXE eingebettete Kopie."""
    for p in (app_dir / VORLAGE_NAME, eingebettet / VORLAGE_NAME):
        if p.is_file():
            return p
    return None


STANDARD_VORLAGE = finde_vorlage() or APP_DIR / VORLAGE_NAME
ICON_DIR = EINGEBETTET_DIR / "assets"


def _dokumente() -> Path:
    if os.name == "nt":
        import ctypes
        buf = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
            return Path(buf.value)
    return Path.home() / "Documents"


def _beschreibbar(ordner: Path) -> bool:
    try:
        with tempfile.TemporaryFile(dir=ordner):
            return True
    except OSError:
        return False


# Per Installer (Programme-Ordner) installiert: Belege und Ergebnisse liegen unter Dokumente\Tankbelege.
INSTALLIERT = (APP_DIR / "unins000.exe").exists() or not _beschreibbar(APP_DIR)
DATEN_DIR = _dokumente() / "Tankbelege" if INSTALLIERT else APP_DIR
STANDARD_BELEGE = DATEN_DIR / "Belege"
if INSTALLIERT:
    try:
        STANDARD_BELEGE.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def standard_ziel(vorlage: Path | None = None) -> Path:
    programm = {APP_DIR.resolve(), EINGEBETTET_DIR.resolve()}
    eigene = vorlage is not None and Path(vorlage).resolve().parent not in programm
    ordner = Path(vorlage).parent if eigene else DATEN_DIR
    return ordner / f"Tanken_{date.today():%Y_%m}_ausgefuellt.xlsx"


def ki_aus_einstellungen(daten: dict) -> tuple[str, dict[str, dict]]:
    """Gewählter Anbieter und je Anbieter Modell/API-Key/Seitenbild (Key bereits entschlüsselt)."""
    gespeichert = daten.get("ki_anbieter_daten") or {}
    je = {}
    for key, (_, modell, _) in ANBIETER.items():
        g = gespeichert.get(key) or {}
        je[key] = {"modell": g.get("modell") or modell,
                   "api_key": einstellungen.entschluesseln(g.get("api_key", "")),
                   "bild": bool(g.get("bild", key != "ollama"))}
    anbieter = daten.get("ki_anbieter")
    return (anbieter if anbieter in ANBIETER else "aus"), je


def ki_einstellung(anbieter: str, je: dict[str, dict]) -> KiEinstellung:
    d = je.get(anbieter, {})
    return KiEinstellung(anbieter, d.get("modell", ""), d.get("api_key", ""), d.get("bild", True))


class App:
    def __init__(self, root: Tk):
        self.root = root
        root.title("Tankbelege -> Excel")
        root.minsize(720, 480)
        self._setze_icon()
        self.events: queue.Queue = queue.Queue()
        gespeichert = einstellungen.laden()
        self.belege = StringVar(value=gespeichert.get("belege") or
                                (str(STANDARD_BELEGE) if STANDARD_BELEGE.is_dir() else ""))
        self.ziel = StringVar(value=gespeichert.get("ziel") or str(standard_ziel()))
        self.anbieter_key, self.ki_daten = ki_aus_einstellungen(gespeichert)
        self.anbieter = StringVar(value=ANBIETER[self.anbieter_key][0])
        self.modell = StringVar()
        self.api_key = StringVar()
        self.bild = BooleanVar()
        self.status = StringVar(value="Bereit")
        self.letztes_ziel: Path | None = None

        frm = ttk.Frame(root, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)
        rows = [("Belege-Ordner:", self.belege, self._waehle_ordner),
                ("Ziel-Datei:", self.ziel, self._waehle_ziel)]
        for i, (label, var, cmd) in enumerate(rows):
            ttk.Label(frm, text=label).grid(row=i, column=0, sticky="w", pady=3)
            ttk.Entry(frm, textvariable=var).grid(row=i, column=1, sticky="ew", padx=6)
            ttk.Button(frm, text="Auswählen ...", command=cmd).grid(row=i, column=2)
        ttk.Label(frm, text="KI bei unklaren Belegen:").grid(row=2, column=0, sticky="w", pady=(8, 3))
        ki = ttk.Frame(frm)
        ki.grid(row=2, column=1, columnspan=2, sticky="ew", padx=6, pady=(8, 3))
        ki.columnconfigure(3, weight=1)
        self.anbieter_box = ttk.Combobox(ki, textvariable=self.anbieter, state="readonly", width=20,
                                         values=[v[0] for v in ANBIETER.values()])
        self.anbieter_box.grid(row=0, column=0, sticky="w")
        self.anbieter_box.bind("<<ComboboxSelected>>", self._anbieter_gewechselt)
        ttk.Label(ki, text="Modell:").grid(row=0, column=2, padx=(12, 4))
        self.modell_feld = ttk.Entry(ki, textvariable=self.modell)
        self.modell_feld.grid(row=0, column=3, sticky="ew")
        ttk.Label(frm, text="API-Key:").grid(row=3, column=0, sticky="w", pady=3)
        self.key_feld = ttk.Entry(frm, textvariable=self.api_key, show="•")
        self.key_feld.grid(row=3, column=1, sticky="ew", padx=6)
        self.bild_feld = ttk.Checkbutton(frm, text="Seitenbild senden", variable=self.bild)
        self.bild_feld.grid(row=3, column=2, sticky="w")
        self._lade_anbieter()
        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self.start_btn = ttk.Button(btns, text="Start", command=self._start)
        self.start_btn.pack(side="left")
        self.open_btn = ttk.Button(btns, text="Ergebnis öffnen", command=self._oeffnen, state="disabled")
        self.open_btn.pack(side="left", padx=6)
        self.pruef_btn = ttk.Button(btns, text="Gelbe Belege prüfen", command=self._pruefen)
        self.pruef_btn.pack(side="left")
        self.progress = ttk.Progressbar(frm, mode="determinate")
        self.progress.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(10, 2))
        ttk.Label(frm, textvariable=self.status).grid(row=6, column=0, columnspan=3, sticky="w")
        self.log = ScrolledText(frm, height=14, state="disabled", font=("Consolas", 9))
        self.log.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=(6, 0))
        frm.rowconfigure(7, weight=1)
        root.protocol("WM_DELETE_WINDOW", self._schliessen)
        root.after(100, self._poll)

    def _merke_anbieter(self):
        self.ki_daten[self.anbieter_key] = {"modell": self.modell.get().strip(), "api_key": self.api_key.get().strip(),
                                            "bild": self.bild.get()}

    def _lade_anbieter(self):
        d = self.ki_daten[self.anbieter_key]
        self.modell.set(d["modell"])
        self.api_key.set(d["api_key"])
        self.bild.set(d["bild"])
        aus = self.anbieter_key == "aus"
        self.modell_feld.configure(state="disabled" if aus else "normal")
        self.key_feld.configure(state="normal" if ANBIETER[self.anbieter_key][2] else "disabled")
        self.bild_feld.configure(state="disabled" if aus else "normal")

    def _anbieter_gewechselt(self, _event=None):
        self._merke_anbieter()
        self.anbieter_key = next(k for k, v in ANBIETER.items() if v[0] == self.anbieter.get())
        self._lade_anbieter()

    def _einstellungen_speichern(self):
        self._merke_anbieter()
        daten = einstellungen.laden()
        daten.update({
            "belege": self.belege.get(), "ziel": self.ziel.get(), "ki_anbieter": self.anbieter_key,
            "ki_anbieter_daten": {k: {"modell": d["modell"], "bild": d["bild"],
                                      "api_key": einstellungen.verschluesseln(d["api_key"])}
                                  for k, d in self.ki_daten.items()},
        })
        try:
            einstellungen.speichern(daten)
        except OSError as exc:
            self._schreibe(f"Einstellungen konnten nicht gespeichert werden: {exc}")

    def _schliessen(self):
        self._einstellungen_speichern()
        self.root.destroy()

    def _setze_icon(self):
        try:
            if os.name == "nt" and (ICON_DIR / "anna.ico").is_file():
                self.root.iconbitmap(default=str(ICON_DIR / "anna.ico"))
            elif (ICON_DIR / "anna.png").is_file():
                self.icon = PhotoImage(file=str(ICON_DIR / "anna.png"))
                self.root.iconphoto(True, self.icon)
        except Exception:
            pass

    def _waehle_ordner(self):
        p = filedialog.askdirectory(title="Belege-Ordner")
        if p:
            self.belege.set(p)

    def _waehle_ziel(self):
        start = Path(self.ziel.get()) if self.ziel.get() else standard_ziel()
        p = filedialog.asksaveasfilename(title="Ziel-Datei", defaultextension=".xlsx",
                                         initialdir=start.parent, initialfile=start.name,
                                         filetypes=[("Excel", "*.xlsx")], confirmoverwrite=False)
        if p:
            self.ziel.set(p)

    def _schreibe(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _start(self):
        vorlage, belege, ziel = finde_vorlage(), Path(self.belege.get()), Path(self.ziel.get())
        if vorlage is None:
            return messagebox.showerror(
                "Fehler", f"Die fest hinterlegte Excel-Vorlage „{VORLAGE_NAME}“ fehlt im Programmordner "
                f"{APP_DIR}. Bitte Tankbelege neu installieren.")
        if not belege.is_dir():
            return messagebox.showerror("Fehler", "Bitte einen gültigen Belege-Ordner wählen.")
        if not self.ziel.get():
            return messagebox.showerror("Fehler", "Bitte einen Ziel-Dateinamen angeben.")
        if ziel.suffix.lower() != ".xlsx":
            ziel = ziel.with_suffix(".xlsx")
            self.ziel.set(str(ziel))
        if ziel.resolve() == vorlage.resolve():
            return messagebox.showerror("Fehler", "Die Originalvorlage darf nicht überschrieben werden.")
        self._einstellungen_speichern()
        ki = ki_einstellung(self.anbieter_key, self.ki_daten)
        if ANBIETER[ki.anbieter][2] and not ki.api_key:
            return messagebox.showerror("Fehler", f"Für {ANBIETER[ki.anbieter][0]} bitte einen API-Key eintragen "
                                        "oder „Aus (nur OCR)“ wählen.")
        self.start_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.progress["value"] = 0
        self._schreibe(f"--- Start: {belege} ---\nVorlage (fest hinterlegt): {vorlage}\nKI: {ki.beschreibung()}")
        threading.Thread(target=self._arbeite, args=(vorlage, belege, ziel, ki), daemon=True).start()

    def _arbeite(self, vorlage, belege, ziel, ki):
        try:
            erg = verarbeiten(vorlage, belege, ziel, ki,
                              fortschritt=lambda a, g, t: self.events.put(("progress", a, g, t)),
                              log=lambda m: self.events.put(("log", m)))
            self.events.put(("done", erg))
        except Exception as exc:
            self.events.put(("error", f"{exc}\n\n{traceback.format_exc(limit=3)}"))

    def _poll(self):
        try:
            while True:
                ev = self.events.get_nowait()
                if ev[0] == "progress":
                    _, aktuell, gesamt, text = ev
                    self.progress["maximum"] = max(gesamt, 1)
                    self.progress["value"] = aktuell
                    self.status.set(f"{aktuell}/{gesamt} – {text}")
                elif ev[0] == "log":
                    self._schreibe(ev[1])
                elif ev[0] == "done":
                    erg = ev[1]
                    self.letztes_ziel = erg.ziel
                    self._schreibe("\n".join(erg.zusammenfassung()))
                    for n, z in erg.zeilen:
                        self._schreibe(f"  Zeile {n}: {_zeile_text(z, hinweis=True)}")
                    modus = "Angehängt an" if erg.angehaengt else "Gespeichert"
                    self._schreibe(f"{modus}: {erg.ziel}\nPrüfprotokoll: {erg.pruefung}")
                    self.status.set(f"Fertig – {len(erg.zeilen)} Zeilen, {len(erg.hinweise)} Hinweise")
                    self.start_btn.configure(state="normal")
                    self.open_btn.configure(state="normal")
                elif ev[0] == "error":
                    self._schreibe("FEHLER: " + ev[1])
                    self.status.set("Fehler")
                    self.start_btn.configure(state="normal")
                    messagebox.showerror("Fehler", ev[1].split("\n")[0])
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _pruefen(self):
        ziel = self.letztes_ziel or Path(self.ziel.get().strip() or standard_ziel())
        if not ziel.exists():
            return messagebox.showinfo("Gelbe Belege prüfen", f"{ziel.name} gibt es noch nicht – bitte zuerst importieren.")
        try:
            if not gelbe_zeilen(ziel):
                return messagebox.showinfo("Gelbe Belege prüfen", f"In {ziel.name} sind keine gelben Zeilen.")
            belege = Path(self.belege.get().strip()) if self.belege.get().strip() else None
            PruefFenster(self.root, ziel, belege,
                         bei_aenderung=lambda: self._schreibe(f"Prüf-Assistent: Zeile in {ziel.name} gespeichert."))
        except Exception as exc:
            messagebox.showerror("Fehler", str(exc))

    def _oeffnen(self):
        if self.letztes_ziel and self.letztes_ziel.exists():
            if hasattr(os, "startfile"):
                if getattr(sys, "frozen", False):
                    # PyInstaller setzt SetDllDirectory auf _MEIPASS; das erbt Excel/LibreOffice sonst
                    import ctypes
                    ctypes.windll.kernel32.SetDllDirectoryW(None)
                os.startfile(self.letztes_ziel)
            else:
                messagebox.showinfo("Ergebnis", str(self.letztes_ziel))


def cli(argv) -> int:
    ap = argparse.ArgumentParser(description="Tankbelege in die Excel-Vorlage übertragen")
    ap.add_argument("--vorlage", default=str(STANDARD_VORLAGE))
    ap.add_argument("--belege", default=str(STANDARD_BELEGE))
    ap.add_argument("--ziel")
    ap.add_argument("--ki", choices=list(ANBIETER), help="KI-Anbieter (Standard: wie in der Oberfläche gespeichert)")
    ap.add_argument("--ollama", action="store_true", help="kurz für --ki ollama")
    ap.add_argument("--modell")
    ap.add_argument("--api-key", help="sonst gespeicherter Key oder Umgebungsvariable TANKBELEGE_API_KEY")
    ap.add_argument("--ohne-bild", action="store_true", help="Seitenbild nicht an die KI senden")
    a = ap.parse_args(argv)
    ziel = Path(a.ziel) if a.ziel else standard_ziel(Path(a.vorlage))
    gespeichert, je = ki_aus_einstellungen(einstellungen.laden())
    ki = ki_einstellung("ollama" if a.ollama else (a.ki or gespeichert), je)
    if a.modell:
        ki.modell = a.modell
    ki.api_key = a.api_key or os.environ.get("TANKBELEGE_API_KEY") or ki.api_key
    if a.ohne_bild:
        ki.bild = False
    try:
        erg = verarbeiten(Path(a.vorlage), Path(a.belege), ziel, ki,
                          fortschritt=lambda x, g, t: print(f"[{x}/{g}] {t}"), log=print)
    except VorlagenFehler as exc:
        print(f"FEHLER: {exc}", file=sys.stderr)
        return 1
    for n, z in erg.zeilen:
        print(f"Zeile {n}: {_zeile_text(z, hinweis=True)}")
    print("\n".join(erg.zusammenfassung()))
    print(f"{'Angehängt an' if erg.angehaengt else 'Gespeichert'}: {erg.ziel}\nPrüfprotokoll: {erg.pruefung}")
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        sys.exit(cli(sys.argv[2:]))
    root = Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
