"""Rechnet aus dem Drehbuch-Soll und der GEMESSENEN Referenzstimme die Laenge,
die jeder Bildabschnitt stehen muss.

Warum nicht einfach das Soll aus dem Drehbuch nehmen: das Soll ist 150 Woerter
pro Minute, gerechnet. Wie lang ein Satz wirklich dauert, misst man. Beides
steht nebeneinander, damit eine Abweichung auffaellt statt stillschweigend
weggeglaettet zu werden.

    video_s = max(soll, gemessen) + handle

`handle` ist der Griff an beiden Enden: Joel spricht das Video selbst ein,
nachtraeglich. Ein Bild, das eine Zehntelsekunde zu frueh wegschneidet, zwingt
ihn zu hetzen. Zu lang stehen zu lassen kostet nur Sekunden am 3:00-Limit.

Aufruf:
    uv run --python 3.11 python docs/video/tools/plan_timing.py
    ... --handle 0.4      (Griff je Abschnitt, Sekunden)
    ... --flip-s 29.0     (gemessene Zeit Klick -> Kante kippt; aus dem Trockenlauf)
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SEGMENTS = ROOT / "docs/video/segments.json"
AUDIO = ROOT / "docs/video/audio"
OUT = ROOT / "docs/video/timing.json"
LIMIT_S = 180.0  # harte Grenze der Einreichung


def probe(path: Path) -> float | None:
    if not path.exists():
        return None
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True)
    return round(float(r.stdout.strip()), 3)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--handle", type=float, default=0.4)
    ap.add_argument("--flip-s", type=float, default=None,
                    help="gemessen: Klick auf Disconnect bis die Kante kippt")
    args = ap.parse_args()

    data = json.loads(SEGMENTS.read_text(encoding="utf-8"))
    rows, total = [], 0.0
    for seg in data["segments"]:
        ref = probe(AUDIO / f"{seg['id']}.wav")
        target = float(seg["target_s"])
        if seg["id"] == "04b-cut":
            # Der 3-Sekunden-Halt aus dem Drehbuch steht MITTEN in diesem
            # Abschnitt ("Watch what does not happen" -- Stille -- Rest).
            # Er ist Stille, also misst ihn keine Tonspur; er muss addiert
            # werden, sonst schneidet das Bild dem Satz das Wort ab.
            video = round((ref or 0.0) + 3.0 + args.handle, 2)
        elif seg["id"] == "04b-remeasure":
            # Der Halt ist nicht Deko, er ist die GEMESSENE Wartezeit der
            # Konsole. Wird sie laenger, wird der Halt laenger -- nie das
            # Bild schneller (Drehbuch: "no cut, no speed-up").
            # Untergrenze: 3 s Stille (der Beat) + der Text, der darueber
            # gesprochen wird.
            floor = 3.0 + (ref or 0.0) + args.handle
            video = round(max(args.flip_s or 0.0, floor), 2)
        elif ref is None:
            video = round(target, 2)
        else:
            # Gemessen schlaegt gerechnet: `target_s` ist 150 Woerter pro
            # Minute auf dem Papier, `reference_s` ist eine Stimme mit einer
            # Stoppuhr daneben.
            video = round(ref + args.handle, 2)
        rows.append({"id": seg["id"], "shot": seg["shot"],
                     "target_s": target, "reference_s": ref, "video_s": video,
                     "script_range": seg["script_range"]})
        total += video

    out = {"handle_s": args.handle, "limit_s": LIMIT_S,
           "total_s": round(total, 2),
           "total_mmss": f"{int(total)//60}:{int(total) % 60:02d}",
           "headroom_s": round(LIMIT_S - total, 2),
           "segments": rows}
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")

    w = max(len(r["id"]) for r in rows)
    print(f"{'id':<{w}}  {'soll':>7} {'gemessen':>9} {'bild':>7}")
    for r in rows:
        ref = "—" if r["reference_s"] is None else f"{r['reference_s']:.2f}"
        print(f"{r['id']:<{w}}  {r['target_s']:>7.2f} {ref:>9} {r['video_s']:>7.2f}")
    print(f"\nGESAMT {out['total_s']:.2f} s = {out['total_mmss']}  "
          f"(Grenze 3:00, Rest {out['headroom_s']:.2f} s)")
    if out["headroom_s"] < 0:
        print("!! UEBER DER GRENZE — kuerzen, nicht beschleunigen.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
