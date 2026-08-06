"""probate start | status | revert"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import hashlib

from probate.campaign import assign, autofill, create_campaign, ensure_owner, verify
from probate.gms import Gms
from probate.parity import compare_schemas, verdict as build_verdict
from probate.ruleset import Rule, evaluate, test_results_aspect
from probate.succession import succeed
from probate.targets import classify, fetch_declared, fetch_measured
from probate.writeback import Writeback

# Default 28080, NICHT 18080: 18080 traegt showcase-ecommerce, gegen das
# datahub-attest veroeffentlichte Zahlen gemessen hat -- nicht verunreinigen
# (dieselbe Regel, die durch die ganze Session gilt). Wer wirklich gegen
# 18080 laufen will, uebergibt --gms explizit.
DEFAULT_GMS = "http://localhost:28080"

# Die drei Regeln, die probate selbst auswertet und als testResults auf den
# Vorgaenger schreibt (Task 7 -- der Auswerter, den DataHub nicht hat).
RULES = [
    Rule("has-successor", "Nachfolger benannt", lambda f: bool(f.get("successor"))),
    Rule("parity-proven", "Gleichwertigkeit bewiesen", lambda f: f.get("parity_ok") is True),
    Rule("all-consumers-signed", "Jeder gemessene Konsument hat unterschrieben",
         lambda f: f.get("signed", 0) >= f.get("live_consumers", 0)),
]


def _schema_fields(gms: Gms, urn: str) -> list[dict]:
    """Liest die echte schemaMetadata-Aspekt-Struktur (Feldform live
    verifiziert 2026-08-06: fields[].nativeDataType ist der native Typ als
    Text, type.type ist die interne Union -- nativeDataType passt direkter
    auf compare_schemas' Erwartung als die Union zu entpacken)."""
    aspect = gms.get_aspect("dataset", urn, "schemaMetadata")
    fields = ((aspect or {}).get("value") or {}).get("fields", [])
    return [{"fieldPath": f["fieldPath"], "type": f.get("nativeDataType", "")} for f in fields]


def _slug(urn: str) -> str:
    return hashlib.sha1(urn.encode()).hexdigest()[:12]


def main() -> int:
    p = argparse.ArgumentParser(prog="probate")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start", help="Ablaufplan fuer eine Abloesung erstellen")
    s.add_argument("--from", dest="predecessor", required=True)
    s.add_argument("--to", dest="successor", required=True)
    s.add_argument("--apply", action="store_true", help="wirklich schreiben (Vorgabe: dry-run)")
    s.add_argument("--gms", default=DEFAULT_GMS)

    a = sub.add_parser(
        "apply",
        help="Beweis fuehren, Unterschrift pro Konsument einholen, umschalten -- der ganze Ablauf",
    )
    a.add_argument("--from", dest="predecessor", required=True)
    a.add_argument("--to", dest="successor", required=True)
    a.add_argument("--old-rows", dest="old_rows", type=int, required=True,
                    help="Zeilenzahl des Vorgaengers, gemessen ausserhalb von probate "
                         "(kein Warehouse-Zugriff eingebaut -- Enthaltung statt Erfindung)")
    a.add_argument("--new-rows", dest="new_rows", type=int, required=True)
    a.add_argument("--gms", default=DEFAULT_GMS)

    sub.add_parser("status", help="Stand der laufenden Abloesung")
    r = sub.add_parser("revert", help="alle journalisierten Schreibvorgaenge zuruecknehmen")
    r.add_argument("--gms", default=DEFAULT_GMS)

    args = p.parse_args()

    if args.cmd == "start":
        gms = Gms(args.gms)
        wb = Writeback(gms, dry_run=not args.apply)
        targets = classify(
            declared=fetch_declared(gms, args.predecessor),
            measured=fetch_measured(gms, args.predecessor),
        )
        out = {
            "predecessor": args.predecessor,
            "successor": args.successor,
            "dry_run": wb.dry_run,
            **targets.summary(),
            "live_targets": len(targets.live),
        }
        Path("harness/runs").mkdir(parents=True, exist_ok=True)
        Path("harness/runs/campaign.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "apply":
        gms = Gms(args.gms)
        wb = Writeback(gms, dry_run=False, journal_path="harness/runs/journal.jsonl")
        targets = classify(
            declared=fetch_declared(gms, args.predecessor),
            measured=fetch_measured(gms, args.predecessor),
        )
        live = sorted(targets.live)

        before = {"successor": None, "parity_ok": None, "signed": 0, "live_consumers": len(live)}
        before_aspect = test_results_aspect(evaluate(RULES, before), evaluated_at=0)

        diff = compare_schemas(
            _schema_fields(gms, args.predecessor), _schema_fields(gms, args.successor)
        )
        v = build_verdict(diff, counts={"old": args.old_rows, "new": args.new_rows})

        result = {
            "predecessor": args.predecessor,
            "successor": args.successor,
            "live_consumers": len(live),
            "consumers": live,
            "parity_ok": v.ok,
            "parity_reasons": v.reasons,
            "signed": 0,
        }

        if not v.ok:
            print("REFUSED - keine Umschaltung ohne Beweis:")
            for reason in v.reasons:
                print(f"  - {reason}")
            after_aspect = test_results_aspect(
                evaluate(RULES, {**before, "parity_ok": False}), evaluated_at=0
            )
            wb.aspect("dataset", args.predecessor, "testResults", after_aspect)
            Path("harness/runs").mkdir(parents=True, exist_ok=True)
            Path("harness/runs/testResults-vorher-nachher.json").write_text(
                json.dumps({"vorher": before_aspect, "nachher": after_aspect}, indent=2),
                encoding="utf-8",
            )
            Path("harness/runs/campaign.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 1

        assertion_urn = f"urn:li:assertion:probate-{_slug(args.predecessor)}"
        gms.graphql(f'''mutation {{ upsertCustomAssertion(
            urn: "{assertion_urn}",
            input: {{ entityUrn: "{args.successor}", type: "PARITY",
                      description: "probate: Schema- und Zeilengleichheit gegen den Vorgaenger",
                      platform: {{ urn: "urn:li:dataPlatform:snowflake" }} }}
          ) {{ urn }} }}''')

        succeed(wb, args.predecessor, args.successor, v, [assertion_urn])

        signed = 0
        if live:
            form_id = f"probate-{_slug(args.predecessor)}"
            prompt_id = f"{form_id}-confirm"
            form_urn = create_campaign(
                wb, form_id, "Probate: Umbau bestaetigen",
                [(prompt_id, "urn:li:structuredProperty:probate_migrated")],
            )
            for consumer in live:
                ensure_owner(wb, "dataset", consumer, "urn:li:corpuser:__datahub_system")
                assign(wb, form_urn, [consumer])
                evidence = {"query_log": f"gefunden via fetch_measured auf {args.predecessor}"}
                autofill(wb, form_urn, consumer, prompt_id,
                         "urn:li:structuredProperty:probate_migrated", "migriert", evidence)
                r = verify(wb, form_urn, consumer, evidence)
                if r.applied:
                    signed += 1

        result["signed"] = signed
        after = {"successor": args.successor, "parity_ok": True, "signed": signed, "live_consumers": len(live)}
        after_aspect = test_results_aspect(evaluate(RULES, after), evaluated_at=0)
        wb.aspect("dataset", args.predecessor, "testResults", after_aspect)

        Path("harness/runs").mkdir(parents=True, exist_ok=True)
        Path("harness/runs/testResults-vorher-nachher.json").write_text(
            json.dumps({"vorher": before_aspect, "nachher": after_aspect}, indent=2), encoding="utf-8"
        )
        Path("harness/runs/campaign.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "revert":
        n = Writeback(Gms(args.gms), dry_run=False).revert_all()
        print(f"{n} Schreibvorgaenge zurueckgenommen")
        return 0

    print(Path("harness/runs/campaign.json").read_text(encoding="utf-8"))
    return 0
