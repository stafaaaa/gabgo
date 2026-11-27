"""Tankbelege -> Excel: grafische Oberfläche (Tkinter) und Kommandozeile."""
from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import traceback
from datetime import date
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from verarbeitung import verarbeiten, _zeile_text

APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
STANDARD_VORLAGE = APP_DIR / "Tanken_neu - Kopie.xlsx"
STANDARD_BELEGE = APP_DIR / "Belege"


def standard_ziel(vorlage: Path) -> Path:
    return vorlage.with_name(f"Tanken_{date.today():%Y_%m}_ausgefuellt.xlsx")


class App:
    def __init__(self, root: Tk):
        self.root = root
        root.title("Tankbelege -> Excel")
        root.minsize(720, 480)
        self.events: queue.Queue = queue.Queue()
        self.vorlage = StringVar(value=str(STANDARD_VORLAGE) if STANDARD_VORLAGE.exists() else "")
        self.belege = StringVar(value=str(STANDARD_BELEGE) if STANDARD_BELEGE.is_dir() else "")
        self.ziel = StringVar(value=str(standard_ziel(STANDARD_VORLAGE)) if STANDARD_VORLAGE.exists() else "")
        self.ollama = BooleanVar(value=False)
        self.status = StringVar(value="Bereit")
        self.letztes_ziel: Path | None = None

        frm = ttk.Frame(root, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(1, weight=1)
        rows = [("Excel-Vorlage:", self.vorlage, self._waehle_vorlage),
                ("Belege-Ordner:", self.belege, self._waehle_ordner),
                ("Ziel-Datei:", self.ziel, self._waehle_ziel)]
        for i, (label, var, cmd) in enumerate(rows):
            ttk.Label(frm, text=label).grid(row=i, column=0, sticky="w", pady=3)
            ttk.Entry(frm, textvariable=var).grid(row=i, column=1, sticky="ew", padx=6)
            ttk.Button(frm, text="Auswählen ...", command=cmd).grid(row=i, column=2)
        ttk.Checkbutton(frm, text="Ollama-Fallback (lokal, llama3.2) bei unklaren Belegen",
                        variable=self.ollama).grid(row=3, column=1, columnspan=2, sticky="w", pady=6)
        btns = ttk.Frame(frm)
        btns.grid(row=4, column=0, columnspan=3, sticky="ew")
        self.start_btn = ttk.Button(btns, text="Start", command=self._start)
        self.start_btn.pack(side="left")
        self.open_btn = ttk.Button(btns, text="Ergebnis öffnen", command=self._oeffnen, state="disabled")
        self.open_btn.pack(side="left", padx=6)
        self.progress = ttk.Progressbar(frm, mode="determinate")
        self.progress.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(10, 2))
        ttk.Label(frm, textvariable=self.status).grid(row=6, column=0, columnspan=3, sticky="w")
        self.log = ScrolledText(frm, height=14, state="disabled", font=("Consolas", 9))
        self.log.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=(6, 0))
        frm.rowconfigure(7, weight=1)
        root.after(100, self._poll)

    def _waehle_vorlage(self):
        p = filedialog.askopenfilename(title="Excel-Vorlage", filetypes=[("Excel", "*.xlsx")])
        if p:
            self.vorlage.set(p)
            if not self.ziel.get():
                self.ziel.set(str(standard_ziel(Path(p))))

    def _waehle_ordner(self):
        p = filedialog.askdirectory(title="Belege-Ordner")
        if p:
            self.belege.set(p)

    def _waehle_ziel(self):
        start = Path(self.ziel.get() or self.vorlage.get() or APP_DIR)
        p = filedialog.asksaveasfilename(title="Ziel-Datei", defaultextension=".xlsx",
                                         initialdir=start.parent, initialfile=start.name,
                                         filetypes=[("Excel", "*.xlsx")])
        if p:
            self.ziel.set(p)

    def _schreibe(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _start(self):
        vorlage, belege, ziel = Path(self.vorlage.get()), Path(self.belege.get()), Path(self.ziel.get())
        if not vorlage.is_file():
            return messagebox.showerror("Fehler", "Bitte eine gültige Excel-Vorlage wählen.")
        if not belege.is_dir():
            return messagebox.showerror("Fehler", "Bitte einen gültigen Belege-Ordner wählen.")
        if not self.ziel.get():
            return messagebox.showerror("Fehler", "Bitte einen Ziel-Dateinamen angeben.")
        if ziel.suffix.lower() != ".xlsx":
            ziel = ziel.with_suffix(".xlsx")
            self.ziel.set(str(ziel))
        if ziel.resolve() == vorlage.resolve():
            return messagebox.showerror("Fehler", "Die Originalvorlage darf nicht überschrieben werden.")
        if ziel.exists() and not messagebox.askyesno("Datei existiert", f"{ziel.name} überschreiben?"):
            return
        self.start_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.progress["value"] = 0
        self._schreibe(f"--- Start: {belege} ---")
        threading.Thread(target=self._arbeite, args=(vorlage, belege, ziel, self.ollama.get()),
                         daemon=True).start()

    def _arbeite(self, vorlage, belege, ziel, ollama):
        try:
            erg = verarbeiten(vorlage, belege, ziel, ollama,
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
                    self._schreibe(f"Neue Zeilen: {len(erg.zeilen)}  (Duplikate: {erg.duplikate}, "
                                   f"nicht übernommen: {erg.uebersprungen})")
                    for n, z in erg.zeilen:
                        self._schreibe(f"  Zeile {n}: {_zeile_text(z)}")
                    self._schreibe(f"Gespeichert: {erg.ziel}\nPrüfprotokoll: {erg.pruefung}")
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

    def _oeffnen(self):
        if self.letztes_ziel and self.letztes_ziel.exists():
            if hasattr(os, "startfile"):
                os.startfile(self.letztes_ziel)
            else:
                messagebox.showinfo("Ergebnis", str(self.letztes_ziel))


def cli(argv) -> int:
    ap = argparse.ArgumentParser(description="Tankbelege in die Excel-Vorlage übertragen")
    ap.add_argument("--vorlage", default=str(STANDARD_VORLAGE))
    ap.add_argument("--belege", default=str(STANDARD_BELEGE))
    ap.add_argument("--ziel")
    ap.add_argument("--ollama", action="store_true")
    a = ap.parse_args(argv)
    ziel = Path(a.ziel) if a.ziel else standard_ziel(Path(a.vorlage))
    erg = verarbeiten(Path(a.vorlage), Path(a.belege), ziel, a.ollama,
                      fortschritt=lambda x, g, t: print(f"[{x}/{g}] {t}"), log=print)
    for n, z in erg.zeilen:
        print(f"Zeile {n}: {_zeile_text(z)}")
    print(f"Gespeichert: {erg.ziel}\nPrüfprotokoll: {erg.pruefung}")
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        sys.exit(cli(sys.argv[2:]))
    root = Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
