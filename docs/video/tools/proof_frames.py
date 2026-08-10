"""Einzelbilder zum Durchsehen, bevor irgendetwas hochgeht.

Eine Bildschirmaufnahme kann mehr einfangen als gemeint. Auf diesem Rechner
liegen Wettbewerbsrecherche ueber andere Teams, ein Slack-Kanal mit deren
Ankuendigungen, Mail und Chatverlauf. Deshalb wird fenstergenau aufgenommen --
und deshalb wird das Ergebnis trotzdem angesehen, statt der Technik zu
glauben. Ein Werkzeug, das behauptet zu wirken, ohne dass jemand nachsieht,
ist genau der Fehler, gegen den dieses Projekt antritt.

Zieht Bilder aus jedem Abschnitt plus Anfang/Mitte/Ende des Gesamtschnitts
nach `docs/video/proof/`. Prueffragen, die ein Mensch beantworten muss:

  - kein Chatfenster, kein Slack, kein Mailfenster
  - keine Taskleiste mit fremden Fenstertiteln
  - keine eingeblendete Benachrichtigung
  - im Browser nur der Werkbank-Tab, keine Lesezeichen mit fremden Eintraegen
  - im Terminal kein Rueckscroll mit fremden Befehlen

Aufruf:
    uv run --python 3.11 python docs/video/tools/proof_frames.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VIDEO = ROOT / "docs/video"
PROOF = VIDEO / "proof"


def duration(path: Path) -> float:
    return float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout.strip())


def grab(src: Path, at: float, dst: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", f"{at:.2f}", "-i", str(src), "-frames:v", "1",
                    str(dst)], check=True)


def main() -> int:
    PROOF.mkdir(parents=True, exist_ok=True)
    for old in PROOF.glob("*.png"):
        old.unlink()

    n = 0
    master = VIDEO / "probate-demo-silent.mp4"
    if master.exists():
        d = duration(master)
        for label, at in (("start", 0.5), ("mitte", d / 2), ("ende", d - 1.0)):
            grab(master, at, PROOF / f"00-gesamt-{label}.png")
            n += 1
    for cut in sorted((VIDEO / "cuts").glob("*.mp4")):
        d = duration(cut)
        grab(cut, min(1.0, d / 2), PROOF / f"{cut.stem}-a.png")
        grab(cut, max(0.0, d - 0.6), PROOF / f"{cut.stem}-b.png")
        n += 2

    print(f"{n} Bilder in {PROOF}")
    print("JETZT ANSEHEN. Erst danach ist irgendetwas 'fertig'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
