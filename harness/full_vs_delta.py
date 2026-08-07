"""Die entscheidende Zusatzfrage der Spec (docs/superpowers/specs/
2026-08-06-lineage-truth-design.md, Abschnitt "Der Lasttest"):

  "Ein Vollabgleich darf zwei Stunden dauern, solange der taegliche
  Nachlauf Minuten braucht. Das entscheidet, ob das Werkzeug in einer
  echten Firma benutzbar ist oder nur im Beispiel."

Warum eine EIGENE Datei statt probate/ledger.py oder harness/loadtest.py
zu erweitern (wie ein frueherer Aufgaben-Entwurf vorschlug): beide sind
aktive Fahrspuren anderer, gleichzeitig laufender Aufgaben in diesem
Lauf -- `git status` zeigte probate/ledger.py bereits modifiziert, bevor
diese Aufgabe anfing. Diese Datei importiert nur LESEND aus
harness.loadgen (plan/generate/cleanup) und harness.loadtest (STATS_SUMMARY_Q,
measure, coarse_pass, detail_pass) und aendert an deren Vertrag nichts.

Delta-Definition (verbindlich -- steht auch im Messergebnis selbst, nicht
nur hier, damit die Zahl nicht ohne ihre Definition zitiert werden kann):

  Ein VOLLABGLEICH prueft JEDES Dataset im Katalog: eine `statsSummary`-
  Abfrage pro Tabelle (Coarse-Durchgang, nachweislich linear in der
  Katalog-Groesse -- harness/runs/loadtest_s.json: 50 Calls/1.235s,
  loadtest_m.json: 500 Calls/12.238s, exakt der 10x-Faktor), gefolgt von
  einem Detail-Durchgang (Ko-Okkurrenz) auf die als auffaellig markierten
  Kanten.

  Ein TAEGLICHER NACHLAUF prueft NUR die Teilmenge des Katalogs, die sich
  seit der letzten Markierung (`since_ms`) geaendert haben KOENNTE. Die
  synthetischen Lasttest-Fixtures (harness/loadgen.py) tragen KEIN echtes
  Schreib-Zeitstempel-Feld -- ein echtes "seit since_ms veraendert" laesst
  sich an ihnen nicht messen, ohne loadgen.py anzufassen (Lane-Grenze).
  Als explizit benannte Annaeherung gilt: die neuesten `CHANGE_FRACTION`
  (Vorgabe 2%) der deterministischen Plan-Liste stehen fuer "kuerzlich
  hinzugekommen/veraendert" -- eine plausible Groessenordnung fuer den
  taeglichen Aenderungsanteil eines reifen Datenkatalogs (bei Skala L
  waeren das 100 von 5'000 Tabellen pro Tag), aber eine ANNAEHERUNG, keine
  aus echten Zeitstempeln gemessene Grenze. Wer diese Zahl zitiert, zitiert
  sie mit dieser Einschraenkung.

  `since_ms` selbst ist FALSY-sensitiv (`None` oder `0`): fehlt der Marker
  vom letzten Lauf, gibt es keine Baseline, gegen die "geaendert seit"
  ueberhaupt einen Sinn ergibt -- ohne Marker MUSS ein voller Scan laufen,
  die Delta-Menge ist dann identisch mit der Vollmenge. Das ist kein
  Rand-Fall, sondern der ehrliche Fall "wir wissen nicht, wann zuletzt
  geprueft wurde" (verification.md: "eine gescheiterte Abfrage ist keine
  Abwesenheit" -- hier: ein fehlender Marker ist kein Grund, kleiner zu
  tun als man weiss).

Was NICHT gemessen wird: eine echte, zeitstempel-basierte Aenderungs-
Erkennung gegen eine produktionsartige Instanz mit echten Schreibzeiten.
Das ist ausserhalb des Umfangs dieser Aufgabe (kein Feature bauen, das der
Plan nicht verlangt) -- die Messung beantwortet die Architektur-Frage
("skaliert der Nachlauf mit der TEILMENGE statt mit dem GANZEN Katalog?"),
nicht die Produkt-Frage ("wie erkennt man 'geaendert' in echt?").
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

from harness.loadtest import STATS_SUMMARY_Q, detail_pass, measure

# 2%: siehe Moduldocstring -- eine explizit benannte Annaeherung an den
# taeglichen Aenderungsanteil eines Katalogs, nicht aus Zeitstempeln
# gemessen (die Fixtures tragen keine).
CHANGE_FRACTION = 0.02

DELTA_DEFINITION = (
    "Vollabgleich = statsSummary-Abfrage je Dataset im GESAMTEN Katalog "
    "+ Detail-Durchgang auf dessen auffaellige Kanten. Tagesdelta = "
    "dieselben beiden Durchgaenge, aber nur auf den juengsten "
    f"{CHANGE_FRACTION * 100:.0f}% der Plan-Liste (Annaeherung an 'seit "
    "since_ms geaendert' -- die synthetischen Fixtures tragen kein echtes "
    "Schreib-Zeitstempel-Feld). since_ms falsy (None/0) heisst 'kein "
    "Marker vom letzten Lauf' -> kein Delta moeglich, Delta==Voll."
)


def _delta_targets(scale: str, fraction: float = CHANGE_FRACTION) -> list[str]:
    """Die neuesten `fraction` der deterministischen Plan-Liste -- die
    Fixture-Datasets sind `t00000..t0000N-1` in Anlage-Reihenfolge
    (harness/loadgen.py::plan), das Ende der Liste steht fuer 'zuletzt
    hinzugekommen'. `round()` statt `int()`, damit z.B. 2% von 50 (=1)
    nicht durch Abschneiden auf 0 faellt; `max(1, ...)` sichert zusaetzlich
    mindestens eine Kante, sonst waere ein Delta-Lauf ueber 0 Datasets ein
    Nicht-Test, kein Messergebnis."""
    from harness.loadgen import plan

    datasets = plan(scale)["datasets"]
    n = max(1, min(len(datasets), math.floor(len(datasets) * fraction + 0.5)))
    return datasets[-n:]


def _coarse_over(gms, urns: list[str]) -> dict:
    """Wie `harness.loadtest.coarse_pass`, aber ueber eine EXPLIZITE
    URN-Teilmenge statt ueber den vollen Katalogplan -- `coarse_pass`
    selbst wird nicht angefasst (Lane-Grenze), diese Funktion stellt
    dieselbe Abfrage (STATS_SUMMARY_Q, dieselbe 'auffaellig'-Regel:
    `queryCountLast30Days` fehlt oder 0) nur fuer eine Teilliste."""
    calls, suspicious, chars = 0, [], 0
    for urn in urns:
        data = gms.graphql(STATS_SUMMARY_Q, {"urn": urn})
        calls += 1
        chars += len(str(data))
        summary = ((data.get("dataset") or {}).get("statsSummary") or {})
        if not summary.get("queryCountLast30Days"):
            suspicious.append(urn)
    return {"api_calls": calls, "response_chars": chars, "suspicious": suspicious}


def _pass_over(gms, urns: list[str], detail_sample: int) -> tuple[dict, dict]:
    """Coarse + Detail ueber eine Teilliste, als EIN gemessener Block
    (ein `measure()`-Aufruf) -- damit Vollabgleich und Delta dieselbe Art
    von Messwert (Sekunden, Peak-Speicher, `broke`) tragen und direkt
    vergleichbar sind, statt zwei Einzelmessungen von Hand zu addieren."""

    def _run():
        coarse = _coarse_over(gms, urns)
        sample = coarse["suspicious"][:detail_sample]
        detail = detail_pass(gms, sample)
        return {**coarse, "detail": detail}

    result, m = measure(_run)
    return (result or {"api_calls": 0, "response_chars": 0, "suspicious": [],
                        "detail": {"detail_edges": 0}}), m


def compare_full_vs_delta(gms, scale: str, since_ms: int | None = None,
                           detail_sample: int = 41) -> dict:
    """Misst Vollabgleich gegen Tagesdelta, BEIDE gegen denselben bereits
    geseedeten Katalog (Aufrufer ist fuer `generate()`/`cleanup()`
    zustaendig, s. `main()` unten -- diese Funktion selbst schreibt
    nichts und raeumt nichts auf, sie liest nur).

    `detail_sample` = 41, dieselbe Zahl wie `harness.loadtest.run_stage`
    (aus dem Lastentwurf der Spec: 41 Auffaelligkeiten bei 384 Kanten) --
    fuer den Vollabgleich ist das eine ECHTE Deckelung (der Katalog kann
    mehr Auffaellige haben als das), fuer das Delta bei `CHANGE_FRACTION`
    ist die Deckelung in der Praxis meist gar nicht wirksam, weil die
    Teilmenge selten mehr als 41 Auffaellige enthaelt.

    Ist der Nachlauf nicht billiger, ist GENAU DAS das Ergebnis -- die
    Zahl kommt trotzdem ins Artefakt (Auftrag: 'eine benannte Grenze ist
    ein Ergebnis, eine verschwiegene ist ein Fehler').
    """
    from harness.loadgen import plan

    p = plan(scale)
    full_targets = p["datasets"]
    # since_ms falsy (None/0): kein Marker vom letzten Lauf -> keine
    # Baseline, gegen die 'geaendert seit' irgendetwas bedeutet. Der
    # ehrliche Fall ist dann: voller Scan, Delta == Voll (s. Moduldocstring).
    delta_targets = full_targets if not since_ms else _delta_targets(scale)

    full, m_full = _pass_over(gms, full_targets, detail_sample)
    delta, m_delta = _pass_over(gms, delta_targets, detail_sample)

    speed = round(m_full["seconds"] / m_delta["seconds"], 2) if m_delta["seconds"] else 0.0
    cheaper = speed > 1.0

    if not since_ms:
        verdict = "delta is NOT cheaper — measured, not assumed (kein since_ms-Marker)"
    elif cheaper:
        verdict = f"delta is {speed}x faster"
    else:
        verdict = "delta is NOT cheaper — measured, not assumed"

    full_calls = full["api_calls"] + full["detail"].get("detail_edges", 0)
    delta_calls = delta["api_calls"] + delta["detail"].get("detail_edges", 0)

    return {
        "scale": scale,
        "since_ms": since_ms,
        "delta_definition": DELTA_DEFINITION,
        "change_fraction": CHANGE_FRACTION,
        "full_datasets": len(full_targets),
        "delta_datasets": len(delta_targets),
        f"loadtest_{scale}_full_seconds": m_full["seconds"],
        f"loadtest_{scale}_delta_seconds": m_delta["seconds"],
        f"loadtest_{scale}_full_peak_mb": m_full["peak_memory_mb"],
        f"loadtest_{scale}_delta_peak_mb": m_delta["peak_memory_mb"],
        f"loadtest_{scale}_full_api_calls": full_calls,
        f"loadtest_{scale}_delta_api_calls": delta_calls,
        f"loadtest_{scale}_full_coarse_calls": full["api_calls"],
        f"loadtest_{scale}_delta_coarse_calls": delta["api_calls"],
        f"loadtest_{scale}_full_detail_edges": full["detail"].get("detail_edges", 0),
        f"loadtest_{scale}_delta_detail_edges": delta["detail"].get("detail_edges", 0),
        f"loadtest_{scale}_full_suspicious": len(full["suspicious"]),
        f"loadtest_{scale}_delta_suspicious": len(delta["suspicious"]),
        f"loadtest_{scale}_full_broke": m_full["broke"],
        f"loadtest_{scale}_delta_broke": m_delta["broke"],
        "full_vs_delta_speedup": speed,
        "full_vs_delta_verdict": verdict,
    }


# Schluessel, die `compare_full_vs_delta` bewusst BAR (nicht skalen-
# praefigiert) zurueckgibt -- praktisch fuer einen einzelnen Aufruf, aber
# gefaehrlich fuer `run_and_write`: zwei Aufrufe fuer verschiedene Skalen
# (s und m) in DIESELBE Artefakt-Datei gemergt wuerden sich sonst
# gegenseitig stillschweigend ueberschreiben (`dict.update` kennt keine
# Kollision). `_scope_ambiguous_keys` benennt sie vor dem Schreiben in
# skalen-praefigierte Varianten um -- `delta_definition`/`change_fraction`
# bleiben bewusst bar (echte Konstanten, in jedem Lauf identisch, kein
# Kollisionsrisiko).
_AMBIGUOUS_KEYS = (
    "full_datasets", "delta_datasets", "since_ms",
    "full_vs_delta_speedup", "full_vs_delta_verdict",
)


def _scope_ambiguous_keys(scale: str, out: dict) -> dict:
    scoped = dict(out)
    for key in _AMBIGUOUS_KEYS:
        scoped[f"loadtest_{scale}_{key}"] = scoped.pop(key)
    return scoped


def run_and_write(gms, scale: str, since_ms: int | None, out_path: Path,
                   detail_sample: int = 41) -> dict:
    """Seedet `probate_load`, misst Voll gegen Delta, raeumt auf und
    VERIFIZIERT die Aufraeumung per `get_aspect`-Ruecklese (nie per
    Suche -- der Index hinkt gemessen >30s nach, s. global-constraints.md).
    Schreibt das Ergebnis als Artefakt, unabhaengig vom Cleanup-Ausgang --
    ein Cleanup-Fehler soll die bereits gemessene Zahl nicht verschlucken,
    er wird stattdessen SICHTBAR im selben Artefakt gemeldet.

    `run_seed_*`/`run_cleanup_*` (nicht `delta_seed_*`): diese Zahlen
    gehoeren zum EINMALIGEN Seed/Cleanup DIESES Messlaufs (einmal fuer
    beide Passes zusammen), nicht zur Delta-PASS-Messung selbst
    (`loadtest_{scale}_delta_seconds` etc.) -- ein Name wie
    `delta_seed_seconds` waere mit dem Delta-Pass verwechselbar."""
    from harness.loadgen import cleanup, generate

    seed, m_seed = measure(generate, gms, scale)
    out = compare_full_vs_delta(gms, scale, since_ms, detail_sample)
    out = _scope_ambiguous_keys(scale, out)
    out["seeded"] = True
    out["namespace"] = "probate_load"
    out[f"loadtest_{scale}_run_seed_seconds"] = m_seed["seconds"]
    out[f"loadtest_{scale}_run_seed_broke"] = m_seed["broke"]
    if m_seed["broke"]:
        out[f"loadtest_{scale}_run_seed_error"] = m_seed["error"]

    clean, m_clean = measure(cleanup, gms, scale)
    clean = clean or {}
    out[f"loadtest_{scale}_run_cleanup_verified"] = clean.get("cleanup_verified", False)
    out[f"loadtest_{scale}_run_cleanup_leftover"] = clean.get("cleanup_leftover", 0)
    out[f"loadtest_{scale}_run_cleanup_errors"] = clean.get("cleanup_errors", [])
    out[f"loadtest_{scale}_run_cleanup_broke"] = m_clean["broke"]
    if m_clean["broke"]:
        out[f"loadtest_{scale}_run_cleanup_error"] = m_clean["error"]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        try:
            prior = json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            prior = {}
    else:
        prior = {}
    prior.update(out)
    out_path.write_text(json.dumps(prior, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gms-url", default="http://localhost:28080")
    p.add_argument("--scale", default="s", choices=("s", "m"))
    p.add_argument("--token", default=None)
    p.add_argument("--since-ms", type=int, default=None)
    p.add_argument("--out", default="harness/runs/full-vs-delta.json")
    args = p.parse_args()

    from probate.gms import Gms

    token = args.token if args.token is not None else os.environ.get("DATAHUB_TOKEN")
    gms = Gms(base_url=args.gms_url, token=token)

    since_ms = args.since_ms
    if since_ms is None:
        since_ms = int(time.time() * 1000) - 86_400_000  # "seit gestern"

    artifact = run_and_write(gms, args.scale, since_ms, Path(args.out))
    print(json.dumps(artifact, indent=2, ensure_ascii=False))
    return 1 if artifact.get(f"loadtest_{args.scale}_full_broke") or \
        artifact.get(f"loadtest_{args.scale}_delta_broke") else 0


if __name__ == "__main__":
    sys.exit(main())
