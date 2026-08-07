"""Der Zustands-Uebergangs-Nachweis: eine Kante WECHSELT ihren Zustand,
wenn sich die Welt aendert -- gemessen, nicht behauptet.

WARUM diese Datei existiert: `harness/seedlab_verdicts.py` beweist, dass
die vier Zustaende (`confirmed`/`dead`/`missing`/`unknown`) in einem echten
Lauf AUFTRETEN. Er beweist nicht, dass eine Kante ihren Zustand WECHSELT,
wenn jemand eine Deklaration eintraegt, eine Abfrage anlegt oder die
Nutzungsdaten wegfallen. Genau das ist der Inhalt des Einreichungs-Videos,
und genau das misst dieses Skript -- vorher/nachher, aus dem Register,
nie aus der Antwort des Knopfes.

DIE REGEL, die dieses Skript traegt (`.claude/rules/verification.md`, und
in diesem Projekt zusaetzlich der Produktgegenstand): **ein Knopf, der
"erfolgreich" meldet, ist kein Beleg.** Falle 21 (`UEBERGABE.md`) ist genau
dieser Fehler in Reinform -- HTTP 200, Aspekt zurueckgespiegelt, nichts
geschrieben, stundenlang unbemerkt. Ablauf je Uebergang deshalb:

    Zustand messen -> Aktion ausfuehren -> MINDESTENS 15 s warten
    -> Zustand erneut messen (und weiter messen, bis er sich zeigt oder
       das Zeitbudget reisst)

Alle Messungen der Warteschleife stehen im Artefakt, nicht nur die letzte.
Wer nur die passende Messung behielte, haette gemessen, bis es stimmt.

DERSELBE SCHREIBWEG wie die Oberflaeche: jede Mutation geht durch
`ui.serve.do_action()` -- dieselbe Sperre, dieselbe Existenzpruefung
(`entityExists`), dasselbe Journal (`probate/writeback.py`). Kein zweiter
Schreibpfad daneben. Der einzige Zusatz ist der `partner`-Durchreicher in
`do_action`, damit die Knoepfe auf JEDE der vier Labor-Kanten wirken
koennen und nicht nur auf die eine Demo-Kante der Oberflaeche.

DIE RUECKNAHME ist ebenfalls kein Sonderweg: die vom Lauf angehaengten
Journal-Zeilen werden in eine eigene Datei kopiert und mit dem PRODUKTIVEN
`Writeback.revert_all()` zurueckgerollt. Scoped, weil `harness/runs/
journal.jsonl` aeltere Zeilen aus anderen Laeufen traegt -- ein
`revert_all()` auf der ganzen Datei wuerde fremde Arbeit anfassen.

DIE EINE AUSNAHME, die ehrlich benannt gehoert: die Nutzungs-Zeitreihe
("Warehouse trennen") laeuft NICHT ueber das Journal -- `do_action` loescht
sie per `/entities?action=delete` (so wie `harness/seed_lineage_lab.py::
purge_usage_history`), und ein geloeschter Zeitreihen-Bereich hat keinen
"before"-Aspekt, den man zurueckschreiben koennte. Dieses Skript liest die
Rohzeilen deshalb VOR dem Schnitt und spielt sie danach mit demselben
SDK-Emitter zurueck, mit dem `seed_lineage_lab.py` sie erzeugt hat --
verifiziert gegen die Rohablage, nicht gegen die Aggregation (Falle 19).

WAS DAS SKRIPT NICHT BEWEIST -- und warum das ein Ergebnis ist:
Der Auftrag nannte "confirmed -> dead" durch Kappen der Nutzung. Das ist
mit diesem Klassifikator NICHT erreichbar, und zwar mit Absicht: ohne
Nutzungsfenster gibt es kein `dead`, sondern `unknown` (`probate/ledger.py::
classify_edges`, das Abdeckungs-Gate steht VOR jedem anderen Zweig). Diese
Kerninvariante wird hier aktiv gemessen (Schritt 5: confirmed -> unknown)
statt weggeschrieben. `confirmed -> dead` entsteht stattdessen dort, wo es
hingehoert: die Nutzung bleibt, die PAAR-ABFRAGE verschwindet (Schritt 4).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # fuer `probate.*`/`ui.*` bei Direktlauf

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    DatasetUsageStatisticsClass,
    TimeWindowSizeClass,
)

import ui.serve as serve
from probate.gms import Gms, GmsError, _validate_urn
from probate.ledger import (
    classify_edges,
    fetch_cooccurrence,
    fetch_declared_edges,
    usage_evidence,
)
from probate.writeback import Writeback

MANIFEST_PATH = Path("examples/seedlab-manifest.json")
OUT_PATH = Path("harness/runs/demo-transitions.json")

# Mindestwartezeit nach jeder Mutation, bevor ueberhaupt gemessen wird.
# Nicht verhandelbar: der Graph-/Suchindex hinkt Writes UND Deletes nach
# (Falle 15, ~30 s beobachtet), ein SDK-Schreibvorgang landet in ~15 s
# (Falle 21). Sofort zu messen hiesse, die eigene Messung gegen einen
# bekannten Verzug laufen zu lassen.
SETTLE_MIN_S = 15.0
SETTLE_MAX_S = 150.0
POLL_S = 5.0

_FAR_FUTURE_MS = 4_102_444_800_000  # 2100-01-01 UTC


# --- Messen --------------------------------------------------------------


def measure(gms, upstream: str, downstream: str, now_ms: int) -> dict:
    """Der Zustand EINER Kante, aus denselben vier Funktionen, die auch
    `harness/seedlab_verdicts.py` und die Werkbank benutzen.

    Kein zweiter Klassifikator: `classify_edges` bekommt exakt dieselben
    Eingaben wie im Produktionslauf, nur auf einen Fokus beschraenkt.
    """
    declared = fetch_declared_edges(gms, upstream, count=200)
    cooccurred, queries_seen = fetch_cooccurrence(gms, upstream)

    coverage_by_urn: dict[str, object] = {}
    timeline_by_urn: dict[str, object] = {}
    for target in declared | set(cooccurred):
        cov, tl = usage_evidence(gms, target, now_ms=now_ms)
        coverage_by_urn[target] = cov
        timeline_by_urn[target] = tl

    verdicts = classify_edges(
        focus=upstream, declared=declared, cooccurred=cooccurred,
        coverage_by_urn=coverage_by_urn, timeline_by_urn=timeline_by_urn,
        now_ms=now_ms, queries_seen=queries_seen)
    match = next((v for v in verdicts if v.edge.downstream == downstream), None)

    return {
        # "absent" heisst: die Kante existiert in KEINER der beiden Quellen.
        # Das ist kein fuenfter Zustand des Produkts, sondern die Aussage
        # "ueber diese Kante wird gar nichts behauptet" -- sie darf nicht
        # als `unknown` verkleidet werden.
        "state": match.state if match else "absent",
        "evidence": match.evidence if match else None,
        "declared": downstream in declared,
        "cooccurrence_queries": len(cooccurred.get(downstream, [])),
        "queries_seen": queries_seen,
        "buckets_checked": match.coverage.buckets_seen if match else None,
        "has_window": match.coverage.has_window if match else None,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "now_ms_used": now_ms,
    }


def now_ms_with_offset(offset_days: int) -> int:
    return int(time.time() * 1000) + offset_days * 86_400_000


def measure_until(gms, upstream: str, downstream: str, expect: str,
                  offset_days: int = 0, min_wait_s: float = SETTLE_MIN_S,
                  max_wait_s: float = SETTLE_MAX_S) -> tuple[list[dict], float | None]:
    """Warten, messen, notfalls weiter messen -- und JEDE Messung behalten.

    Rueckgabe: (Messreihe, Sekunden bis zum erwarteten Zustand oder None).
    Die Reihe ist der Beleg dafuer, dass nicht bis zum passenden Ergebnis
    gewuerfelt wurde: steht der erwartete Zustand erst in der dritten
    Messung, ist genau das im Artefakt zu sehen.
    """
    series: list[dict] = []
    t0 = time.monotonic()
    time.sleep(min_wait_s)
    reached: float | None = None
    while True:
        m = measure(gms, upstream, downstream, now_ms_with_offset(offset_days))
        elapsed = round(time.monotonic() - t0, 1)
        series.append({"seconds_after_action": elapsed, **m})
        if m["state"] == expect:
            reached = elapsed
            break
        if time.monotonic() - t0 >= max_wait_s:
            break
        time.sleep(POLL_S)
    return series, reached


# --- Rohe Nutzungs-Zeitreihe lesen und zurueckspielen ---------------------


def read_usage_rows(gms, urn: str) -> list[dict]:
    """Die Rohablage, nicht die Aggregation (Falle 19: die GraphQL-
    Aggregation hinkte live >75 s nach). Derselbe Weg wie
    `harness/seed_lineage_lab.py::_raw_usage_values`."""
    _validate_urn(urn)
    payload = {"urn": urn, "entity": "dataset", "aspect": "datasetUsageStatistics",
               "startTimeMillis": 0, "endTimeMillis": _FAR_FUTURE_MS,
               "limit": 200}  # Falle 14: `limit` ist Pflicht, sonst HTTP 500
    status, body = gms._send("POST", f"{gms.base}/aspects?action=getTimeseriesAspectValues", payload)
    if status != 200 or not isinstance(body, dict):
        raise GmsError(f"getTimeseriesAspectValues HTTP {status}: {str(body)[:200]}")
    out = []
    for v in ((body.get("value") or {}).get("values")) or []:
        raw = v.get("aspect", {}).get("value")
        out.append(json.loads(raw) if isinstance(raw, str) else raw)
    return out


def restore_usage_rows(emitter: DatahubRestEmitter, urn: str, rows: list[dict]) -> int:
    """Spielt exakt die vorher gelesenen Zeilen zurueck -- Zeitstempel,
    Granularitaet und beide Zaehler unveraendert. Keine erfundenen Werte:
    was nicht in `rows` stand, wird auch nicht geschrieben."""
    written = 0
    for row in rows:
        gran = row.get("eventGranularity") or {}
        aspect = DatasetUsageStatisticsClass(
            timestampMillis=row["timestampMillis"],
            eventGranularity=TimeWindowSizeClass(
                unit=gran.get("unit", "DAY"), multiple=gran.get("multiple", 1)),
            uniqueUserCount=row.get("uniqueUserCount"),
            totalSqlQueries=row.get("totalSqlQueries"),
        )
        emitter.emit_mcp(MetadataChangeProposalWrapper(entityUrn=urn, aspect=aspect))
        written += 1
    return written


def usage_signature(rows: list[dict]) -> dict:
    """Die Signatur muss den Unterschied sehen, den sie zu sehen behauptet.

    Erste Fassung trug nur Zeilenzahl, Gesamtsumme und die Zeitstempel --
    ein eigener Test (`tests/test_demo_transitions.py`) hat gezeigt, dass
    zwei vertauschte Bucket-Werte (5/6 statt 6/5) damit als "identisch
    wiederhergestellt" durchgegangen waeren. Genau die Sorte Pruefung, die
    aussieht wie eine Verifikation und keine ist. Jetzt steht jede Zeile
    einzeln drin: Zeitstempel, Abfragen, Nutzer.
    """
    return {
        "rows": len(rows),
        "total_sql_queries": sum(r.get("totalSqlQueries") or 0 for r in rows),
        "buckets": sorted(
            [r.get("timestampMillis"), r.get("totalSqlQueries"), r.get("uniqueUserCount")]
            for r in rows
        ),
    }


# --- Journal: nur die eigenen Zeilen, mit dem produktiven Rueckwaertsgang -


def journal_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def revert_journal_slice(gms, lines: list[str], scratch: Path) -> int:
    """`Writeback.revert_all()` -- der produktive Rueckwaertsgang -- auf
    eine Kopie GENAU der Zeilen, die dieser Lauf angehaengt hat."""
    if not lines:
        return 0
    scratch.parent.mkdir(parents=True, exist_ok=True)
    scratch.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return Writeback(gms, dry_run=False, journal_path=str(scratch)).revert_all()


# --- Der Lauf ------------------------------------------------------------


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def run(gms, manifest_path: Path, out_path: Path, scratch_dir: Path,
        min_wait_s: float = SETTLE_MIN_S) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_state = {e["expected_edge_state"]: e for e in manifest["edges"]}
    journal_path = Path(serve.JOURNAL_PATH)

    confirmed = by_state["confirmed"]
    dead = by_state["dead"]
    missing = by_state["missing"]
    unknown = by_state["unknown"]

    steps: list[dict] = []
    notes: list[str] = []

    def note(text, number=None):  # die Signatur, die `do_action` erwartet
        _log(f"    aktion: {text}")

    def do_step(title: str, from_state: str, to_state: str, mechanism: str,
                edge: dict, act, offset_days_before: int = 0,
                offset_days_after=0) -> dict:
        """`offset_days_after` darf eine Funktion sein: die Sicht-
        Verschiebung von `fast-forward` steht erst NACH der Aktion fest,
        und sie vorher zu raten waere genau die Sorte Annahme, gegen die
        dieses Skript geschrieben ist."""
        up, down = edge["upstream_urn"], edge["downstream_urn"]
        _log(f"{title}  ({from_state} -> {to_state})")
        before = measure(gms, up, down, now_ms_with_offset(offset_days_before))
        _log(f"    vorher gemessen: {before['state']}")

        journal_before = journal_lines(journal_path)
        t_act = time.monotonic()
        result = act()
        act_seconds = round(time.monotonic() - t_act, 2)
        journal_after = journal_lines(journal_path)
        new_lines = journal_after[len(journal_before):]

        offset_after = (offset_days_after() if callable(offset_days_after)
                        else offset_days_after)
        series, reached = measure_until(gms, up, down, to_state,
                                        offset_days=offset_after,
                                        min_wait_s=min_wait_s)
        after = series[-1]
        proven = before["state"] == from_state and after["state"] == to_state
        _log(f"    nachher gemessen: {after['state']} nach {after['seconds_after_action']}s "
             f"-- {'BEWIESEN' if proven else 'NICHT BEWIESEN'}")

        step = {
            "title": title, "from_expected": from_state, "to_expected": to_state,
            "mechanism": mechanism,
            "upstream_urn": up, "downstream_urn": down,
            "action_result": result,
            "action_seconds": act_seconds,
            "journal_lines_added": len(new_lines),
            "view_offset_days_after": offset_after,
            "state_before": before["state"], "state_after": after["state"],
            "seconds_to_expected_state": reached,
            "proven": proven,
            "measurement_before": before,
            "measurement_series_after": series,
        }
        steps.append(step)
        return step

    # ---- Schritt 1 + 2: missing <-> confirmed --------------------------
    # Die Kante wird BENUTZT (Paar-Abfrage vorhanden), aber nirgends
    # deklariert. Eintragen macht sie `confirmed`, die Ruecknahme macht sie
    # wieder `missing`.
    j_before_1 = journal_lines(journal_path)
    do_step(
        "1 · Kante eintragen", "missing", "confirmed",
        "ui.serve.do_action('add-edge') schreibt upstreamLineage auf das Ziel",
        missing,
        lambda: serve.do_action("add-edge", gms, missing["upstream_urn"], note,
                                partner=missing["downstream_urn"]))
    slice_1 = journal_lines(journal_path)[len(j_before_1):]

    do_step(
        "2 · Eintrag zuruecknehmen", "confirmed", "missing",
        "Writeback.revert_all() auf die Journal-Zeilen aus Schritt 1",
        missing,
        lambda: {"reverted_entries": revert_journal_slice(
            gms, slice_1, scratch_dir / "revert-step1.jsonl")})

    # ---- Schritt 3 + 4: dead <-> confirmed -----------------------------
    # Die Kante ist deklariert, die Nutzung ist gemessen -- aber im
    # geprueften Fenster hat keine Abfrage beide Tabellen zusammen
    # beruehrt. Eine neue Paar-Abfrage deckt sie; ihre Ruecknahme nimmt die
    # Deckung wieder weg. DAS ist `confirmed -> dead`: die Deklaration
    # bleibt, der Beleg verschwindet -- und die Nutzungsfenster bleiben
    # stehen, sonst waere es `unknown` (siehe Schritt 5).
    j_before_3 = journal_lines(journal_path)
    do_step(
        "3 · Abfrage anlegen, die beide Tabellen beruehrt", "dead", "confirmed",
        "ui.serve.do_action('seed-query') schreibt eine Query mit zwei Subjects",
        dead,
        lambda: serve.do_action("seed-query", gms, dead["upstream_urn"], note,
                                partner=dead["downstream_urn"]))
    slice_3 = journal_lines(journal_path)[len(j_before_3):]

    do_step(
        "4 · Abfrage wieder entfernen", "confirmed", "dead",
        "Writeback.revert_all() auf die Journal-Zeilen aus Schritt 3",
        dead,
        lambda: {"reverted_entries": revert_journal_slice(
            gms, slice_3, scratch_dir / "revert-step3.jsonl")})

    # ---- Schritt 5 + 6: confirmed <-> unknown --------------------------
    # Der Auftrag nannte hier "confirmed -> dead". Gemessen wird `unknown`,
    # und das ist die Kerninvariante des Produkts, kein Fehlschlag: ohne
    # Nutzungsfenster gibt es keine Grundlage fuer "tot".
    confirmed_down = confirmed["downstream_urn"]
    usage_before = read_usage_rows(gms, confirmed_down)
    sig_before = usage_signature(usage_before)
    _log(f"Nutzungs-Zeitreihe vor dem Schnitt: {sig_before['rows']} Zeilen, "
         f"{sig_before['total_sql_queries']} Abfragen")
    if not usage_before:
        raise SystemExit(
            "abgebrochen: das confirmed-Ziel traegt keine Nutzungszeilen -- ein "
            "Schnitt waere nicht zurueckspielbar (und die Kante waere schon jetzt unknown)")

    do_step(
        "5 · Warehouse trennen (Nutzungsdaten verschwinden)", "confirmed", "unknown",
        "ui.serve.do_action('cut-warehouse') loescht die Nutzungs-Zeitreihe des Ziels",
        confirmed,
        lambda: serve.do_action("cut-warehouse", gms, confirmed["upstream_urn"], note,
                                partner=confirmed_down))

    emitter = DatahubRestEmitter(gms_server=gms.base)
    do_step(
        "6 · Warehouse wieder anschliessen", "unknown", "confirmed",
        "dieselben Rohzeilen per SDK-Emitter zurueckgespielt (Zeitstempel unveraendert)",
        confirmed,
        lambda: {"rows_restored": restore_usage_rows(emitter, confirmed_down, usage_before)})

    usage_after = read_usage_rows(gms, confirmed_down)
    sig_after = usage_signature(usage_after)
    usage_restored = sig_after == sig_before
    if not usage_restored:
        notes.append(
            f"Nutzungs-Zeitreihe NICHT identisch wiederhergestellt: vorher {sig_before}, "
            f"nachher {sig_after} -- harness/seed_lineage_lab.py neu laufen lassen")

    # ---- Schritt 7: unknown bleibt unknown -----------------------------
    # Die Zeit vorspulen aendert am Urteil nichts, weil es fuer diese Kante
    # nie ein Nutzungsfenster gab. Genau hier trennt sich das Produkt von
    # jedem Werkzeug, das Stille als Tod liest.
    do_step(
        "7 · Zeit 30 Tage vorspulen", "unknown", "unknown",
        "ui.serve.do_action('fast-forward') verschiebt nur die Sicht, schreibt nichts",
        unknown,
        lambda: serve.do_action("fast-forward", gms, unknown["upstream_urn"], note),
        offset_days_before=0,
        offset_days_after=lambda: serve._view_offset_days)
    serve.reset_view_offset(note)

    # ---- Aufraeumen zurueckgelesen -------------------------------------
    _log("Endzustand aller vier Labor-Kanten wird gemessen ...")
    final_states = {}
    cleanup_ok = True
    for label, edge in by_state.items():
        m = measure(gms, edge["upstream_urn"], edge["downstream_urn"], now_ms_with_offset(0))
        final_states[label] = {"expected": label, "state": m["state"],
                               "matches": m["state"] == label,
                               "evidence": m["evidence"]}
        cleanup_ok = cleanup_ok and m["state"] == label
        _log(f"    {label}: {m['state']} {'OK' if m['state'] == label else 'ABWEICHUNG'}")

    # Die Zahl kommt aus den beiden tatsaechlich abgegriffenen Slices, nicht
    # aus einer Differenz der Dateilaenge -- eine parallele Lane koennte in
    # derselben Sekunde eine eigene Zeile angehaengt haben.
    lines_added = len(slice_1) + len(slice_3)
    lines_reverted = sum(
        s["action_result"].get("reverted_entries", 0)
        for s in steps if isinstance(s["action_result"], dict)
        and "reverted_entries" in s["action_result"])

    proven = [s for s in steps if s["proven"]]
    artifact = {
        "seeded": True,
        "seeded_statement": manifest.get("seeded_statement", ""),
        "gms_url": gms.base,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "transitions_manifest": manifest_path.as_posix(),
        "transitions_settle_seconds_minimum": min_wait_s,
        "transitions_attempted": len(steps),
        "transitions_proven": len(proven),
        "transitions_all_proven": len(proven) == len(steps),
        "transitions_cleanup_verified": bool(cleanup_ok and usage_restored),
        "transitions_journal_lines_added": lines_added,
        "transitions_journal_lines_reverted": lines_reverted,
        "transitions_usage_rows_cut_and_restored": sig_before["rows"],
        "transitions_usage_timeseries_identical_after_restore": usage_restored,
        "transitions_states_reached": ",".join(s["state_after"] for s in steps),
        "usage_signature_before_cut": sig_before,
        "usage_signature_after_restore": sig_after,
        "steps": steps,
        "final_states": final_states,
        "notes": notes,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    return artifact


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gms-url", default="http://localhost:28080")
    p.add_argument("--manifest", default=str(MANIFEST_PATH))
    p.add_argument("--out", default=str(OUT_PATH))
    # Die Journal-Ausschnitte fuer den Rueckwaertsgang sind Arbeitsmaterial,
    # kein Beleg -- sie gehoeren nicht neben die Lauf-Artefakte in
    # harness/runs/, wo sie als Messergebnis missverstanden wuerden.
    p.add_argument("--scratch", default=str(Path(tempfile.gettempdir()) / "probate-transitions"))
    p.add_argument("--settle-seconds", type=float, default=SETTLE_MIN_S)
    p.add_argument("--token", default=None)
    args = p.parse_args(argv)

    if args.settle_seconds < SETTLE_MIN_S:
        raise SystemExit(
            f"--settle-seconds {args.settle_seconds} verweigert: unter {SETTLE_MIN_S}s "
            "misst man den Index-Verzug, nicht die Wirkung (Falle 15/21)")

    # Dieselbe Sperre wie die Werkbank: nie 18080 (fremde Messdaten),
    # nie 8080 (fremder Dienst), nie ein fremder Host.
    serve._validate_gms_target(args.gms_url)

    token = args.token if args.token is not None else os.environ.get("DATAHUB_TOKEN")
    gms = Gms(base_url=args.gms_url, token=token)

    artifact = run(gms, Path(args.manifest), Path(args.out),
                   Path(args.scratch), min_wait_s=args.settle_seconds)

    print()
    for s in artifact["steps"]:
        mark = "BEWIESEN     " if s["proven"] else "NICHT BEWIESEN"
        print(f"  {mark}  {s['title']:<48} {s['state_before']} -> {s['state_after']} "
              f"({s['seconds_to_expected_state']}s)")
    print(f"\n  {artifact['transitions_proven']}/{artifact['transitions_attempted']} Uebergaenge bewiesen, "
          f"Aufraeumung {'zurueckgelesen' if artifact['transitions_cleanup_verified'] else 'FEHLGESCHLAGEN'}")
    print(f"  Artefakt: {args.out}")
    for n in artifact["notes"]:
        print(f"  HINWEIS: {n}")
    return 0 if (artifact["transitions_all_proven"] and artifact["transitions_cleanup_verified"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
