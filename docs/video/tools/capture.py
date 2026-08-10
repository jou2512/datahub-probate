"""Bildaufnahme — FENSTERGENAU, niemals der Desktop.

Warum diese Datei ueberhaupt existiert: `-i desktop` nimmt alles auf, was
gerade offen ist. Auf diesem Rechner liegen Wettbewerbsrecherche ueber andere
Teams, ein Slack-Kanal mit deren Ankuendigungen, Mail und Chatverlauf. Nichts
davon darf in einem Video landen, das oeffentlich auf YouTube geht. Deshalb
ist `-i desktop` hier ausgeschlossen, nicht nur unerwuenscht.

`gdigrab` kann fenstergenau: `-i title=<Fenstertitel>`. Der Titel wird EINMAL
beim Start aufgeloest (`FindWindow` in `read_header`); aendert die Seite
danach ihren Titel, bleibt die Aufnahme am selben Fenster. Gemessen und
bestaetigt am 10.08.2026.

Zwei Fallen, beide gemessen:

1. **Chrome liefert schwarze Bilder**, wenn er auf der GPU zeichnet -- GDI
   sieht dann nichts. Deshalb startet Chrome fuer den Dreh mit
   `--disable-gpu`. Ohne das ist die Aufnahme schwarz, und zwar lautlos.
2. **Ein hart abgeschossenes ffmpeg hinterlaesst eine kaputte .mp4** (der
   moov-Atom fehlt, die Datei ist unlesbar). Die Rohaufnahme laeuft deshalb
   nach **.mkv** -- ein Format, das jederzeit abbrechbar ist -- und ffmpeg
   bekommt zum Schluss ein `q` auf die Eingabe, kein Kill.

Die dritte Sache: **wann faengt die Aufnahme an?** Marken sind relativ zur Uhr
des Steuerskripts, der Schnitt aber relativ zum ersten Bild. Der naheliegende
Weg -- warten, bis die Datei waechst -- ist FALSCH: gemessen 10.08.2026 lag
der so bestimmte Nullpunkt **5.2 s** zu frueh, weil der Muxer seinen Kopf
schreibt, lange bevor das erste Bild darin steht. Jeder Schnitt sass damit
fuenf Sekunden daneben, und zwar unauffaellig.

Deshalb wird der Versatz nicht am Anfang geraten, sondern am ENDE gerechnet:
    versatz = laenge(aufnahme) - (laufzeit_des_skripts + nachlauf)
Beide Summanden misst das Skript selbst. `start()` wartet nur noch darauf,
dass ffmpeg ueberhaupt laeuft.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

FPS = 30


def start(out_path: Path, window_title: str) -> tuple[subprocess.Popen, float]:
    """Startet die Aufnahme des Fensters `window_title`. Gibt (Prozess, t0)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    args = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "gdigrab", "-framerate", str(FPS), "-draw_mouse", "1",
        "-i", f"title={window_title}",
        # Fenstermasse koennen um ein Pixel schwanken; hier festnageln, sonst
        # scheitert das Zusammenlegen an unterschiedlichen Groessen.
        "-vf", "scale=1920:1080:flags=lanczos,setsar=1",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16",
        "-pix_fmt", "yuv420p", "-an", str(out_path),
    ]
    proc = subprocess.Popen(args, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    # Kurz hinsehen, ob ffmpeg ueberhaupt laeuft. Nicht mehr: auf das erste
    # geschriebene Bild zu warten war der urspruengliche Versuch und ist
    # zweimal schiefgegangen -- einmal 5.2 s zu frueh (Muxer-Kopf), einmal
    # gar nicht (ein fast unbewegtes Terminalbild erreicht in 20 s keine
    # 8 KB, und die Aufnahme lief dann verwaist weiter). Der Versatz kommt
    # ohnehin vom Ende her, also braucht der Anfang keine Erkennung.
    time.sleep(1.0)
    if proc.poll() is not None:
        err = (proc.stderr.read() or b"").decode("utf-8", "replace")
        raise RuntimeError(
            f"ffmpeg beendete sich sofort — Fenster '{window_title}' "
            f"nicht gefunden?\n{err.strip()[:400]}")
    return proc, time.perf_counter()


def stop(proc: subprocess.Popen) -> None:
    """Sauber beenden: `q` auf die Eingabe, dann warten."""
    try:
        proc.stdin.write(b"q")
        proc.stdin.flush()
    except Exception:
        pass
    try:
        proc.wait(timeout=15)
    except Exception:
        proc.terminate()
        proc.wait(timeout=10)
