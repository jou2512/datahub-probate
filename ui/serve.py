"""Der Live-Modus der Werkbank.

Warum diese Datei existiert -- zwei Gruende, beide zwingend:

1. CORS. Ein Browser auf file:// oder einem fremden Port braucht von GMS
   einen Access-Control-Allow-Origin-Kopf. Ob 28080 den sendet, ist NICHT
   gemessen. Ein Proxy im selben Ursprung loescht die Frage, statt sie zu
   beantworten.
2. Die Knoepfe sind Python. "Kante eintragen" ist kein GMS-Aufruf, sondern
   correct.apply_proposal() ueber writeback.Writeback -- mit Journal,
   Vorher-Sicherung und Rueckwaertsgang. Diese Disziplin im Browser
   nachzubauen waere eine zweite Wahrheit ueber den einzigen Schreibweg.

Port 8899: nicht 8080 (WhatsApp-Bridge), nicht 8081 (existiert nicht),
nicht 3000 (Cockpit).
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT_DEFAULT = 8899

ACTIONS = ("seed-query", "add-edge", "remove-edge",
           "cut-warehouse", "fast-forward", "run-ledger")

UI_DIR = Path(__file__).parent


def route(method: str, path: str, query: dict) -> tuple[str, dict]:
    """Wegewahl ohne Socket -- damit sie ohne Netz pruefbar ist."""
    if path == "/api/mode" and method == "GET":
        return "mode", {}
    if path == "/api/ledger" and method == "GET":
        return "ledger", {}
    if path == "/api/log" and method == "GET":
        return "log", {"since": int((query.get("since") or ["0"])[0])}
    if path.startswith("/api/action/"):
        name = path.rsplit("/", 1)[-1]
        if name not in ACTIONS:
            raise KeyError(f"unbekannte Aktion: {name}")
        if method != "POST":
            raise ValueError("Aktionen schreiben -- nur POST")
        return "action", {"name": name}
    raise KeyError(f"kein Weg fuer {method} {path}")


def do_action(name: str, gms, focus: str, note) -> dict:
    """Absichtlich nur ein Platzhalter. Das Ausfuehren der sechs Knoepfe
    (seed-query/add-edge/remove-edge/cut-warehouse/fast-forward/run-ledger)
    ist Task 19 -- der Schreibweg fuehrt ueber probate.writeback.Writeback
    und darf nicht vorab in Task 18 erfunden werden. Ein klarer Fehler
    statt eines stillen No-ops, falls jemand vor Task 19 einen Knopf drueckt.
    """
    raise NotImplementedError(
        f"aktion '{name}' -- do_action ist Task 19, noch nicht gebaut"
    )


def build_handler(gms_url: str, focus: str, log: list):
    """Baut die Handler-Klasse erst hier, nicht auf Modulebene -- damit
    `import ui.serve` (fuer route()/ACTIONS/PORT_DEFAULT in den Tests)
    nicht schon ein GMS/Writeback-Geflecht mitzieht, das ohne laufende
    Instanz gar nicht existieren muss."""
    from probate.gms import Gms

    def note(text: str, number=None) -> None:
        """Jede Protokollzeile traegt eine Zahl, kein Gefuehl."""
        log.append({"t": int(time.time() * 1000), "text": text, "n": number})

    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(UI_DIR), **kw)

        def _json(self, payload, code=200):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _handle(self, method):
            u = urlparse(self.path)
            try:
                kind, args = route(method, u.path, parse_qs(u.query))
            except (KeyError, ValueError):
                return None
            gms = Gms(gms_url)
            if kind == "mode":
                return self._json({"mode": "live", "gms": gms_url, "focus": focus})
            if kind == "log":
                return self._json({"entries": log[args["since"]:], "cursor": len(log)})
            if kind == "ledger":
                # Erst hier importiert, nicht auf Modul-/Handler-Ebene:
                # probate.ledger.run() ist Task 17 und existiert zum
                # Zeitpunkt von Task 18 noch nicht (Lanes laufen
                # parallel). Ein spaeter Import laesst /api/mode,
                # /api/log und die statische Auslieferung schon jetzt
                # funktionieren, statt den ganzen Server an einer
                # Funktion scheitern zu lassen, die dieser Task nicht
                # baut.
                from probate.ledger import run as ledger_run
                out = ledger_run(gms, focus, int(time.time() * 1000))
                note(f"full check: {out['edges_total']} edges", out["edges_total"])
                return self._json(out)
            if kind == "action":
                return self._json(do_action(args["name"], gms, focus, note))
            return None

        def do_GET(self):
            if self._handle("GET") is None:
                super().do_GET()

        def do_POST(self):
            if self._handle("POST") is None:
                self.send_error(404)

        def log_message(self, fmt, *a):
            """Stdlib loggt jeden Request auf stderr -- unterdrueckt, weil
            `note()`/log[] bereits das sichtbare Protokoll der Werkbank ist
            und ein zweites, unstrukturiertes Protokoll nur Rauschen waere."""
            pass

    return H


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="ui.serve",
        description="Werkbank-Proxy: serviert ui/ statisch und reicht "
                     "API-Aufrufe an GMS/probate weiter (CORS geloescht "
                     "statt beantwortet).",
    )
    parser.add_argument("--gms", default="http://localhost:28080",
                         help="GMS-Basis-URL (Standard: http://localhost:28080)")
    parser.add_argument("--focus", default="",
                         help="URN der im Fokus stehenden Tabelle")
    parser.add_argument("--port", type=int, default=PORT_DEFAULT)
    args = parser.parse_args(argv)

    log: list = []
    handler_cls = build_handler(args.gms, args.focus, log)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_cls)
    print(f"werkbank live: http://127.0.0.1:{args.port} -- gms {args.gms}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
