"""Legt die Referenzsaetze auf die Zeitachse des Schnitts -- eine Fuehrungsspur.

Wozu: Joel spricht selbst. Diese Spur sagt ihm, WANN welcher Satz faellt und
wie viel Luft dahinter ist. Er kann sie beim Aufnehmen auf einem Ohr laufen
lassen oder einfach vorher einmal hoeren.

Sie ist ausserdem der Rueckfall, wenn seine Aufnahme scheitert: laenge und
Abschnittsgrenzen stimmen dann schon.

Der Beat in `04b-cut` ist bewusst Stille -- der Satz beginnt am Anfang des
Abschnitts, die drei Sekunden Halt sitzen danach.

Aufruf:
    uv run --python 3.11 python docs/video/tools/reference_track.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VIDEO = ROOT / "docs/video"
AUDIO = VIDEO / "audio"
OUT = AUDIO / "reference-track.wav"


def main() -> int:
    timing = json.loads((VIDEO / "timing.json").read_text(encoding="utf-8"))
    rows = timing["segments"]

    inputs, filters, labels = [], [], []
    start = 0.0
    plan = []
    for i, r in enumerate(rows):
        wav = AUDIO / f"{r['id']}.wav"
        if wav.exists():
            idx = len(inputs) // 2   # zwei Listeneintraege je Eingang ("-i", Pfad)
            inputs += ["-i", str(wav)]
            filters.append(f"[{idx}:a]aresample=48000,adelay="
                           f"{int(start * 1000)}|{int(start * 1000)}[a{idx}]")
            labels.append(f"[a{idx}]")
            plan.append((r["id"], start, r["reference_s"], r["video_s"]))
        start += r["video_s"]

    if not labels:
        print("Keine Referenz-Wavs. Erst reference_voice.ps1 laufen lassen.")
        return 1

    mix = ("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:"
           f"dropout_transition=0,apad,atrim=0:{start:.3f}[out]")
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs,
         "-filter_complex", ";".join(filters) + ";" + mix,
         "-map", "[out]", "-ar", "48000", "-ac", "1", str(OUT)], check=True)

    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(OUT)],
        capture_output=True, text=True, check=True).stdout.strip())

    print(f"{'Abschnitt':<18}{'beginnt':>9}{'spricht':>9}{'Bild':>8}{'Luft':>8}")
    for sid, at, ref, vid in plan:
        print(f"{sid:<18}{at:>9.2f}{ref:>9.2f}{vid:>8.2f}{vid - ref:>8.2f}")
    print(f"\nFuehrungsspur: {OUT}   gemessen {dur:.3f} s "
          f"(Bild soll {start:.2f} s sein)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
