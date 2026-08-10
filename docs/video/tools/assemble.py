"""Schneidet die Rohaufnahmen an den Marken auseinander und legt den Schnitt.

Eingang:
  docs/video/raw/console.mp4      + docs/video/marks-console.json
  docs/video/raw/terminal-*.mp4   + docs/video/marks-terminal-*.json
  docs/video/cuts/09-endcard.mp4  (endcard.py)

Ausgang:
  docs/video/cuts/<nn>-<abschnitt>.mp4   je Abschnitt, einzeln austauschbar
  docs/video/probate-demo-silent.mp4     der stumme Schnitt in Drehbuchfolge

Warum einzeln: Joel spricht nachtraeglich. Spricht er einen Satz neu, tauschen
wir genau einen Abschnitt und legen neu zusammen -- statt alles neu zu drehen.

Aufruf:
    uv run --python 3.11 python docs/video/tools/assemble.py
    ... --drop 05-transitions      (Abschnitt weglassen, wenn es eng wird)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VIDEO = ROOT / "docs/video"
RAW, CUTS = VIDEO / "raw", VIDEO / "cuts"
LIMIT_S = 180.0

# Die Reihenfolge des Schnitts. Nicht die Aufnahmereihenfolge -- die Konsole
# wird in einem Zug gedreht, das Terminal in einem zweiten.
ORDER = ["01-payoff", "02-seeded", "03-dead-edge", "04a-flip-before", "04b-cut",
         "04c-reveal", "05-transitions", "06-model", "07-gate", "07b-mcp",
         "08-close", "09-endcard"]


def probe(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return round(float(out.strip()), 3)


def spans(marks_file: Path, raw: Path) -> dict[str, tuple[float, float]]:
    """Anfang/Ende je Abschnitt, IN DER ZEIT DER AUFNAHME.

    Der Versatz zwischen der Uhr des Steuerskripts und der Aufnahme wird vom
    ENDE her gerechnet, nicht am Anfang geraten (Begruendung in capture.py:
    ein am Dateiwachstum bestimmter Nullpunkt lag 5.2 s daneben).
    """
    data = json.loads(marks_file.read_text(encoding="utf-8"))
    segs = [m for m in data["marks"] if m["kind"] == "segment"]
    end_all = max(m["t"] for m in data["marks"])
    offset = probe(raw) - (data.get("total_s", end_all) + data.get("tail_s", 0.0))
    if offset < -0.05:
        print(f"  !! Aufnahme ist KUERZER als der Ablauf ({offset:+.2f} s) — "
              "ffmpeg hat Bilder verloren oder wurde zu frueh beendet.")
    print(f"  Versatz Aufnahme↔Ablauf: {offset:+.3f} s")
    out = {}
    for i, m in enumerate(segs):
        stop = segs[i + 1]["t"] if i + 1 < len(segs) else end_all
        out[m["name"]] = (max(0.0, m["t"] + offset), stop + offset)
    return out


def cut(src: Path, start: float, stop: float, dst: Path) -> float:
    """Genau schneiden heisst neu kodieren. Ein Kopier-Schnitt springt zum
    naechsten Schluesselbild und verschiebt den Ton um bis zu zwei Sekunden."""
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-ss", f"{start:.3f}", "-i", str(src), "-t", f"{stop - start:.3f}",
         "-c:v", "libx264", "-preset", "slow", "-crf", "18",
         "-pix_fmt", "yuv420p", "-r", "30", "-an", str(dst)],
        check=True)
    return probe(dst)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop", action="append", default=[])
    ap.add_argument("--out", default=str(VIDEO / "probate-demo-silent.mp4"))
    ap.add_argument("--skip-cut", action="store_true",
                    help="vorhandene cuts/ verwenden, nur neu zusammenlegen")
    args = ap.parse_args()
    CUTS.mkdir(parents=True, exist_ok=True)

    if not args.skip_cut:
        sources = []
        for marks in sorted(VIDEO.glob("marks-*.json")):
            stem = marks.stem.replace("marks-", "")
            raw = RAW / f"{stem}.mkv"
            if not raw.exists():
                print(f"übersprungen: {raw.name} fehlt (zu {marks.name})")
                continue
            sources.append((raw, marks))
        if not sources:
            print("Keine Rohaufnahme gefunden. Erst aufnehmen "
                  "(docs/video/tools/record.ps1).")
            return 1
        for raw, marks in sources:
            for name, (a, b) in spans(marks, raw).items():
                dst = CUTS / f"{name}.mp4"
                d = cut(raw, a, b, dst)
                print(f"  {name:<18} {a:7.2f}–{b:7.2f}  →  {dst.name}  {d:6.2f} s")

    parts, total = [], 0.0
    for name in ORDER:
        if name in args.drop:
            print(f"  {name:<18} WEGGELASSEN (--drop)")
            continue
        f = CUTS / f"{name}.mp4"
        if not f.exists():
            print(f"!! {name}: {f} fehlt — der Schnitt waere unvollstaendig.")
            return 2
        d = probe(f)
        parts.append(f)
        total += d

    listing = CUTS / "_concat.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts),
                       encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c:v", "libx264", "-preset", "slow", "-crf", "18",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", args.out],
        check=True)
    measured = probe(Path(args.out))
    mm, ss = int(measured) // 60, int(measured) % 60
    print(f"\nStummer Schnitt: {args.out}")
    print(f"GEMESSEN {measured:.3f} s = {mm}:{ss:02d}   "
          f"(Grenze 3:00, Rest {LIMIT_S - measured:.2f} s)")
    if measured > LIMIT_S:
        print("!! UEBER 3:00 — Ausschluss. Einen Abschnitt mit --drop kuerzen.")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
