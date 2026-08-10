"""Der Ledger-Lauf ueber den Demo-Katalog -- und die Messung, ob die
Konsole diese Menge traegt.

WARUM diese Datei zusaetzlich zu `harness/record_ledger.py` existiert:
jene zeichnet die VIER geseedeten Fokusse des Labors auf. Sie ist der
Beweis (je eine Kante pro Zustand), aber sie ist keine Demo -- bei vier
Zeilen hat kein Filter, kein Baum, keine Sortierung und keine
Seitenaufteilung einen Grund zu existieren (`docs/werkbank-spec.md`,
"Der Massstab"). Dieses Skript laeuft ueber den Demo-Katalog aus
`harness/seed_demo_catalog.py`: mehrere hundert Kanten ueber vier
Plattformen und fuenf Datenbanken.

**Die vier Labor-Fokusse laufen ausdruecklich MIT.** Zwei Gruende, beide
belegbar:

1. Sie sind der Zustands-Beweis. Ein Register, das die vier abgenommenen
   Kanten nicht enthaelt, wirft den staerksten Beleg des Projekts weg.
2. `ui/serve.py::load_recorded_ledger` waehlt den Startzustand der Konsole
   nach `(passende Fokus-Tabellen, Umfang, Zeitstempel)` -- in DIESER
   Reihenfolge, `matched` zuerst. Ein Artefakt ohne die Labor-Fokusse
   haette `matched == 0` und verloere gegen jedes Ein-Kanten-Protokoll,
   das sie nennt, egal wie gross es ist. Mit allen vier ist `matched`
   maximal, der Umfang ohnehin, und `focus_mismatch` (der Warnstreifen
   "Aufzeichnung betrifft Tabellen, die es so nicht mehr gibt") bleibt
   aus. Nicht angenommen, sondern nachgeprueft: `--verify-console` startet
   einen Server auf einem eigenen Port und liest, welchen Stand er laedt.

Das Artefakt landet unter `harness/runs/` und traegt `seeded: true` samt
Satz (`UEBERGABE.md` §7.3) -- eine Aufzeichnung, die wie eine frische
Messung aussieht, waere genau die Behauptung ohne Beleg, gegen die dieses
Produkt antritt.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # fuer `probate.*` bei Direktlauf

from harness.record_ledger import combine_runs  # noqa: E402
from probate.gms import Gms  # noqa: E402
from probate.ledger import run as ledger_run  # noqa: E402
from ui import console_api  # noqa: E402

DEMO_MANIFEST = Path("examples/demo-catalog-manifest.json")
SEEDLAB_MANIFEST = Path("examples/seedlab-manifest.json")
DEFAULT_OUT = Path("harness/runs/demo-katalog-ledger.json")
SEED_ARTIFACT = Path("harness/runs/demo-katalog-seed.json")
CLAIMS_OUT = Path("harness/runs/demo-katalog-claims.json")

# Schluessel, die `combine_runs` OHNE Praefix schreibt, weil die Werkbank
# genau diese Namen liest (`edges_total`, `edges_dead`, ...). Sie duerfen
# nicht in die Beleg-Pruefung: `harness/runs/ledger.json` traegt dieselben
# Namen mit anderen Werten (ein Fokus, eine Kante), und
# `audit_claims.load_runs` bricht bei zwei verschiedenen Werten unter
# demselben Namen ab -- zu Recht, das ist die Wachfunktion. Fuer die Prosa
# gibt es deshalb eine eigene, durchgehend praefigierte Abschrift
# (`demo-katalog-claims.json`): dieselben gemessenen Zahlen, nur unter
# Namen, die keiner anderen Behauptung im Weg stehen.
_UNPREFIXED_TO_CLAIMABLE = {
    "edges_total": "demo_ledger_edges_total",
    "edges_confirmed": "demo_ledger_edges_confirmed",
    "edges_dead": "demo_ledger_edges_dead",
    "edges_missing": "demo_ledger_edges_missing",
    "edges_unknown": "demo_ledger_edges_unknown",
    "coverage_buckets_seen": "demo_ledger_coverage_buckets_seen",
    "api_calls": "demo_ledger_api_calls",
    "queries_seen": "demo_ledger_queries_seen",
}
_CLAIM_PREFIXES = ("demo_ledger_", "demo_catalog_", "manifest_", "console_")

SEEDED_STATEMENT = (
    "A real run against synthetic "
    "Demonstrationsdaten (harness/seed_demo_catalog.py, Namensraum "
    "probate_demo_*, plus das Vier-Zustaende-Labor probate_seedlab) -- keine "
    "echte Warehouse-Nutzung."
)


def load_focuses(demo: Path, seedlab: Path) -> tuple[list[str], list[str]]:
    """Beide Fokus-Listen, getrennt gehalten. Getrennt, weil der Bericht
    sagen koennen muss, wie viele Kanten aus dem Labor stammen und wie
    viele aus dem Demo-Katalog -- eine gemischte Zahl waere nicht
    zerlegbar."""
    demo_focuses = sorted(json.loads(demo.read_text(encoding="utf-8"))["focuses"])
    lab = json.loads(seedlab.read_text(encoding="utf-8"))
    lab_focuses = [e["upstream_urn"] for e in lab["edges"] if e.get("upstream_urn")]
    return demo_focuses, lab_focuses


def measure_console(edges: list[dict], gms: Gms | None, repeats: int = 5) -> dict:
    """Was die Konsole SERVERSEITIG tut, bei dieser Menge gemessen.

    `ui/console_api.py` ist die Schicht, die filtert, sortiert und
    seitenweise schneidet -- genau das, was bei vier Zeilen gratis ist und
    bei mehreren hundert die Antwortzeit bestimmt. Gemessen wird der
    Median mehrerer Laeufe, nicht ein einzelner (ein Einzelwert auf einer
    Maschine mit laufenden Containern ist Rauschen, kein Messwert).
    """
    def timed(fn, n=repeats) -> float:
        samples = []
        for _ in range(n):
            t0 = time.perf_counter()
            fn()
            samples.append((time.perf_counter() - t0) * 1000)
        return round(statistics.median(samples), 2)

    out = {
        "console_edges_measured": len(edges),
        "console_ms_facets": timed(lambda: console_api.facets(edges)),
        "console_ms_page_unfiltered": timed(
            lambda: console_api.filter_sort_page(edges, {}, {"count": "50"})),
        "console_ms_page_state_filter": timed(
            lambda: console_api.filter_sort_page(edges, {}, {"state": "dead,missing", "count": "50"})),
        "console_ms_page_sorted_last": timed(
            lambda: console_api.filter_sort_page(edges, {}, {"sort": "last", "dir": "desc", "count": "50"})),
        "console_ms_page_freetext": timed(
            lambda: console_api.filter_sort_page(edges, {}, {"q": "fct_", "count": "50"})),
        "console_ms_evidence_all": timed(lambda: console_api.evidence(edges, {})),
    }
    if gms is not None:
        known = {e["downstream"]: e["state"] for e in edges}
        out["console_ms_catalog_page"] = timed(
            lambda: console_api.catalog_page(gms, "*", 0, 50, known), n=3)
        out["console_ms_catalog_total"] = timed(
            lambda: console_api.catalog_total(gms, "*"), n=3)
        out["console_catalog_total"] = console_api.catalog_total(gms, "*")
    return out


def compare_with_manifest(edges: list[dict], manifest_path: Path) -> dict:
    """Gemessenes Urteil gegen die Erwartung des Manifests.

    Eine Abweichung ist ein BEFUND, kein Grund, das Manifest anzupassen
    (`.claude/rules/verification.md`). Sie wird gezaehlt, nach Paaren
    aufgeschluesselt und in den Bericht geschrieben.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {(e["upstream_urn"], e["downstream_urn"]): e["expected_state"]
                for e in manifest["edges"]}
    measured = {(e["upstream"], e["downstream"]): e["state"] for e in edges}

    matched = mismatched = 0
    absent: list[str] = []
    confusion: dict[str, int] = {}
    for key, want in expected.items():
        got = measured.get(key)
        if got is None:
            absent.append(f"{key[0]} -> {key[1]}")
            continue
        if got == want:
            matched += 1
        else:
            mismatched += 1
            confusion[f"{want}->{got}"] = confusion.get(f"{want}->{got}", 0) + 1
    return {
        "manifest_edges": len(expected),
        "manifest_edges_matched": matched,
        "manifest_edges_mismatched": mismatched,
        "manifest_edges_absent": len(absent),
        "manifest_absent_sample": absent[:10],
        "manifest_confusion": confusion,
        "manifest_all_matched": mismatched == 0 and not absent,
    }


def verify_console_pick(port: int, timeout_s: float = 40.0) -> dict:
    """Startet `ui/serve.py` auf einem EIGENEN Port und liest, welchen
    Stand die Konsole beim Start laedt.

    Nachpruefen statt annehmen (Auftrag, woertlich): die Auswahllogik ist
    `(matched, len(edges), generated_at_ms)`, und ob dieses Artefakt
    gewinnt, entscheidet die Platte -- nicht diese Datei. Der Port ist
    bewusst NICHT 8899/8898: dort laeuft die Werkbank-Spur.
    """
    import subprocess

    proc = subprocess.Popen(
        [sys.executable, "-m", "ui.serve", "--port", str(port)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        def get(path: str, timeout: int) -> tuple[dict, float]:
            # `X-Probate: 1` ist Pflicht fuer JEDE Methode unter /api/*
            # (`ui/serve.py::_enforce_request_origin`) -- ohne den Kopf
            # antwortet der Server mit HTTP 403, und ein Messversuch ohne
            # ihn misst nur die eigene Nachlaessigkeit. Live gestolpert,
            # 07.08.: erster Versuch 403 "x-probate-header fehlt".
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}{path}",
                headers={"X-Probate": "1", "Host": f"127.0.0.1:{port}"})
            t1 = time.perf_counter()
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode())
            return data, round((time.perf_counter() - t1) * 1000, 1)

        t0 = time.perf_counter()
        last_err = ""
        while time.perf_counter() - t0 < timeout_s:
            try:
                body, cold_ms = get("/api/current", 10)
                # Der ERSTE Treffer traegt den Start des Servers mit (Laden
                # und Ranken aller Artefakte von der Platte). Ihn als
                # "Antwortzeit der Konsole" auszugeben waere eine Zahl mit
                # falschem Nenner -- deshalb kalt UND warm, beide benannt.
                warm_current = [get("/api/current", 10)[1] for _ in range(5)]
                conns, _ = get("/api/connections?count=50", 20)
                warm_conn = [get("/api/connections?count=50", 20)[1] for _ in range(5)]
                warm_filtered = [
                    get("/api/connections?count=50&state=dead,missing&sort=last&dir=desc", 20)[1]
                    for _ in range(5)]
                warm_catalog = [get("/api/catalog?count=50", 30)[1] for _ in range(3)]
                http_ms = round(statistics.median(warm_current), 1)
                conn_ms = round(statistics.median(warm_conn), 1)
                prov = body.get("provenance") or body
                return {
                    "console_started": True,
                    "console_error": "",
                    "console_recorded_from": prov.get("recorded_from")
                        or body.get("recorded_from", ""),
                    "console_recorded_at_iso": prov.get("recorded_at_iso")
                        or body.get("recorded_at_iso", ""),
                    "console_focus_mismatch": bool(
                        prov.get("focus_mismatch", body.get("focus_mismatch"))),
                    "console_edges_total": body.get("edges_total"),
                    "console_http_ms_current_cold": cold_ms,
                    "console_http_ms_current": http_ms,
                    "console_http_ms_connections": conn_ms,
                    "console_http_ms_connections_filtered_sorted": round(
                        statistics.median(warm_filtered), 1),
                    "console_http_ms_catalog": round(statistics.median(warm_catalog), 1),
                    "console_connections_total": conns.get("total"),
                    "console_connections_rows": len(conns.get("rows") or []),
                }
            except Exception as exc:  # noqa: BLE001 -- Startfenster, wird gleich wiederholt
                last_err = f"{type(exc).__name__}: {exc}"
                time.sleep(1.0)
        return {"console_started": False, "console_error": last_err}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            proc.kill()


def write_claims_artifact(ledger: dict, seed_path: Path = SEED_ARTIFACT,
                          out: Path = CLAIMS_OUT) -> dict:
    """Die zitierfaehige Abschrift: nur Skalare, nur unter praefigierten
    Namen, aus BEIDEN Artefakten (Seed und Lauf).

    Warum ueberhaupt eine zweite Datei: `harness/audit_claims.py` merged
    alle bekannten Lauf-Artefakte zu EINER Zahlen-Tabelle und bricht ab,
    wenn zwei Artefakte denselben Namen mit verschiedenen Werten tragen.
    Das Lauf-Artefakt muss `edges_total` heissen (die Werkbank liest es),
    `harness/runs/ledger.json` traegt denselben Namen mit dem Wert 1. Beide
    haben recht -- sie reden nur ueber verschiedene Laeufe. Statt eine der
    beiden Wahrheiten zu verbiegen, bekommt die Prosa eine eigene
    Abschrift mit eindeutigen Namen. Freitexte und Listen bleiben draussen:
    sie sind Kontext einer Behauptung, nicht die Behauptung.
    """
    claims: dict = {
        "seeded": True,
        "seeded_statement": SEEDED_STATEMENT,
        "generated_at": ledger.get("recorded_at_iso", ""),
    }
    if seed_path.exists():
        seed_art = json.loads(seed_path.read_text(encoding="utf-8"))
        for k, v in seed_art.items():
            if k.startswith("demo_catalog_") and isinstance(v, (int, float, bool, str)):
                claims[k] = v
    for k, v in ledger.items():
        if not isinstance(v, (int, float, bool, str)):
            continue
        if k.startswith(_CLAIM_PREFIXES):
            claims[k] = v
    for src, dst in _UNPREFIXED_TO_CLAIMABLE.items():
        if src in ledger:
            claims[dst] = ledger[src]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(claims, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    return claims


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gms", default="http://localhost:28080")
    p.add_argument("--token", default=None)
    p.add_argument("--demo-manifest", default=str(DEMO_MANIFEST))
    p.add_argument("--seedlab-manifest", default=str(SEEDLAB_MANIFEST))
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--limit-focuses", type=int, default=0,
                   help="nur die ersten N Demo-Fokusse (Vormessung)")
    p.add_argument("--verify-console", action="store_true",
                   help="Server auf --console-port starten und pruefen, "
                        "welchen Stand er laedt")
    p.add_argument("--verify-console-only", action="store_true",
                   help="nur die Konsolen-Pruefung gegen das bestehende "
                        "Artefakt, ohne neuen Ledger-Lauf")
    p.add_argument("--console-port", type=int, default=8901)
    args = p.parse_args(argv)

    if args.gms not in ("http://localhost:28080", "http://127.0.0.1:28080"):
        print("VERWEIGERT: nur localhost:28080 ist erlaubt.", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    if args.verify_console_only:
        # Wiederholbar ohne den 25-s-Lauf: die Auswahl der Konsole haengt
        # an dem, was auf der Platte liegt, nicht daran, ob gerade gemessen
        # wurde. Ein zweiter Ledger-Lauf nur fuer diese Frage waere Zeit
        # ohne Erkenntnis.
        out = json.loads(out_path.read_text(encoding="utf-8"))
        out.update(verify_console_pick(args.console_port))
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        write_claims_artifact(out)
        print(json.dumps({k: v for k, v in out.items()
                          if k.startswith("console_")}, indent=2, ensure_ascii=False))
        return 0 if out.get("console_started") else 1

    token = args.token if args.token is not None else os.environ.get("DATAHUB_TOKEN")
    gms = Gms(base_url=args.gms, token=token)

    demo_focuses, lab_focuses = load_focuses(
        Path(args.demo_manifest), Path(args.seedlab_manifest))
    if args.limit_focuses:
        demo_focuses = demo_focuses[: args.limit_focuses]
    focuses = demo_focuses + lab_focuses

    now_ms = int(time.time() * 1000)
    print(f"  {len(focuses)} Fokusse ({len(demo_focuses)} Demo-Katalog, "
          f"{len(lab_focuses)} Labor) gegen {args.gms}")

    t0 = time.perf_counter()
    runs = []
    for i, focus in enumerate(focuses, 1):
        runs.append(ledger_run(gms, focus, now_ms))
        if i % 50 == 0 or i == len(focuses):
            done = time.perf_counter() - t0
            print(f"    {i}/{len(focuses)} Fokusse, {done:.1f}s "
                  f"({done / i:.2f}s je Fokus)")
    ledger_seconds = round(time.perf_counter() - t0, 2)

    out = combine_runs(runs)
    out["recorded_at_iso"] = datetime.now(timezone.utc).isoformat()
    out["seeded_statement"] = SEEDED_STATEMENT
    out["demo_ledger_seconds"] = ledger_seconds
    out["demo_ledger_focuses"] = len(focuses)
    out["demo_ledger_focuses_demo_catalog"] = len(demo_focuses)
    out["demo_ledger_focuses_seedlab"] = len(lab_focuses)
    out["demo_ledger_seconds_per_focus"] = round(ledger_seconds / max(1, len(focuses)), 3)

    lab_prefix = "probate_seedlab."
    out["demo_ledger_edges_from_seedlab"] = sum(
        1 for e in out["edges"] if lab_prefix in e["upstream"])
    out["demo_ledger_edges_from_demo_catalog"] = (
        out["edges_total"] - out["demo_ledger_edges_from_seedlab"])

    parts = [console_api.split_urn(e["upstream"]) for e in out["edges"]]
    parts += [console_api.split_urn(e["downstream"]) for e in out["edges"]]
    out["demo_ledger_platforms"] = len({p["platform"] for p in parts if p["platform"]})
    out["demo_ledger_databases"] = len({p["database"] for p in parts if p["database"]})
    out["demo_ledger_tables"] = len({p["qualified"] for p in parts if p["qualified"]})

    out.update(compare_with_manifest(out["edges"], Path(args.demo_manifest)))
    out.update(measure_console(out["edges"], gms))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")

    if args.verify_console:
        print(f"\n  Starte Konsole auf Port {args.console_port} und lese den Startzustand ...")
        out.update(verify_console_pick(args.console_port))
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")

    write_claims_artifact(out)

    summary = {k: v for k, v in out.items() if k not in ("edges", "focuses")}
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\n  Artefakt: {out_path}")

    if not out["manifest_all_matched"]:
        print("\n  BEFUND: gemessene Zustaende weichen vom Manifest ab -- "
              "siehe manifest_confusion / manifest_absent_sample. "
              "Das Manifest wird NICHT nachtraeglich angepasst.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
