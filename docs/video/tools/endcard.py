"""Endkarte: drei Zeilen, dunkler Grund, in Sekunden neu gerendert.

Warum ein Skript und kein Bild: die Repo-Adresse ist ein Parameter. Benennt
Joel das Repo um, ist die Karte einen Aufruf spaeter neu -- nicht eine
Bildbearbeitung spaeter.

Farben und Schrift kommen aus `ui/werkbank.css` (dunkles Thema), damit die
Karte nicht wie ein Fremdkoerper hinter der Konsole steht:
    Grund  #101318 (--bg-dark)   Text #e9ecf1 (--ink-dark)
    matt   #9ba4b1 (--ink-muted-dark)   Akzent #6d92dd (--accent-dark)
Kein Farbverlauf, kein Emoji, nicht alles zentriert (werkbank-spec.md,
Ebene 3, Joels AI-Slop-Verbot).

Aufruf:
    uv run --python 3.11 python docs/video/tools/endcard.py
    ... --repo-url https://github.com/…   ... --seconds 3   ... --png-only
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "docs/video/cuts"

BG, INK, MUTED, ACCENT = "0x101318", "0xe9ecf1", "0x9ba4b1", "0x6d92dd"
W, H, FPS = 1920, 1080, 30

# Windows-Schriften. ffmpeg will den Doppelpunkt im Pfad entwertet sehen.
FONT_REG = "C\\:/Windows/Fonts/segoeui.ttf"
FONT_BOLD = "C\\:/Windows/Fonts/segoeuib.ttf"
FONT_MONO = "C\\:/Windows/Fonts/consola.ttf"


def esc(text: str) -> str:
    """drawtext frisst `:` und `'` nicht roh."""
    return (text.replace("\\", "\\\\").replace(":", "\\:")
                .replace("'", "’").replace(",", "\\,"))


def build_filter(repo_url: str, licence: str, seeded: str) -> str:
    left = 200
    parts = [
        # Akzent-Haarlinie ueber dem Block -- ein Strich, kein Kasten.
        f"drawbox=x={left}:y=392:w=120:h=3:color={ACCENT}:t=fill",
        f"drawtext=fontfile='{FONT_MONO}':text='{esc(repo_url)}'"
        f":fontcolor={INK}:fontsize=52:x={left}:y=452",
        f"drawtext=fontfile='{FONT_BOLD}':text='{esc(licence)}'"
        f":fontcolor={MUTED}:fontsize=40:x={left}:y=548",
        f"drawtext=fontfile='{FONT_REG}':text='{esc(seeded)}'"
        f":fontcolor={MUTED}:fontsize=40:x={left}:y=612",
    ]
    return ",".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-url", default="https://github.com/jou2512/datahub-probate")
    ap.add_argument("--licence", default="Apache 2.0")
    ap.add_argument("--seeded", default="All usage data in this video is seeded.")
    ap.add_argument("--seconds", type=float, default=3.0)
    ap.add_argument("--png-only", action="store_true")
    ap.add_argument("--out", default=str(OUT_DIR / "09-endcard.mp4"))
    ap.add_argument("--png", default=str(OUT_DIR / "09-endcard.png"))
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    vf = build_filter(args.repo_url, args.licence, args.seeded)
    src = f"color=c={BG}:s={W}x{H}:r={FPS}"

    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"{src}:d=1",
                    "-vf", vf, "-frames:v", "1", args.png],
                   check=True, capture_output=True)
    print(f"PNG   {args.png}")
    if args.png_only:
        return 0

    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"{src}:d={args.seconds}",
                    "-vf", vf, "-c:v", "libx264", "-preset", "slow", "-crf", "16",
                    "-pix_fmt", "yuv420p", "-r", str(FPS), args.out],
                   check=True, capture_output=True)
    d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", args.out],
                       capture_output=True, text=True, check=True).stdout.strip()
    print(f"MP4   {args.out}   gemessen {float(d):.3f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
