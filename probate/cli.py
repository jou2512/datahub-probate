"""probate start | apply | confirm | status | revert"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import hashlib

from probate.campaign import assign, autofill, create_campaign, ensure_owner, verify
from probate.gms import Gms
from probate.ledger import run as ledger_run
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

CAMPAIGN_STATE = Path("harness/runs/campaign.json")

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


def _signed_count(gms: Gms, form_urn: str, consumers: list[str]) -> list[str]:
    """Fragt DataHub direkt, welche Konsumenten das Formular WIRKLICH
    abgeschlossen haben (dataset.forms.completedForms) -- probate behauptet
    keinen Signatur-Status, es liest ihn aus dem Katalog zurueck.
    """
    signed = []
    for c in consumers:
        d = gms.graphql(
            'query($urn: String!) { dataset(urn: $urn) { forms { completedForms { form { urn } } } } }',
            {"urn": c},
        )
        completed = ((d.get("dataset") or {}).get("forms") or {}).get("completedForms") or []
        if any((f.get("form") or {}).get("urn") == form_urn for f in completed):
            signed.append(c)
    return signed


def _rewrite_test_results(wb: Writeback, predecessor: str, successor: str, live: list[str], signed: list[str]) -> dict:
    facts = {
        "successor": successor,
        "parity_ok": True,
        "signed": len(signed),
        "live_consumers": len(live),
    }
    aspect = test_results_aspect(evaluate(RULES, facts), evaluated_at=0)
    wb.aspect("dataset", predecessor, "testResults", aspect)
    return aspect


def main() -> int:
    p = argparse.ArgumentParser(prog="probate")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start", help="Ablaufplan fuer eine Abloesung erstellen")
    s.add_argument("--from", dest="predecessor", required=True)
    s.add_argument("--to", dest="successor", required=True)
    s.add_argument("--apply", action="store_true", help="wirklich schreiben (Vorgabe: dry-run)")
    s.add_argument("--gms", default=DEFAULT_GMS)
    s.add_argument("--token", default=None, help="Personal Access Token; sonst DATAHUB_TOKEN aus der Umgebung")

    a = sub.add_parser(
        "apply",
        help="Beweis fuehren, Kampagne anlegen und Konsumenten VORSCHLAGEN -- signiert NICHT selbst",
    )
    a.add_argument("--from", dest="predecessor", required=True)
    a.add_argument("--to", dest="successor", required=True)
    a.add_argument("--old-rows", dest="old_rows", type=int, required=True,
                    help="Zeilenzahl des Vorgaengers, gemessen ausserhalb von probate "
                         "(kein Warehouse-Zugriff eingebaut -- Enthaltung statt Erfindung)")
    a.add_argument("--new-rows", dest="new_rows", type=int, required=True)
    a.add_argument("--gms", default=DEFAULT_GMS)
    a.add_argument("--token", default=None, help="Personal Access Token; sonst DATAHUB_TOKEN aus der Umgebung")

    c = sub.add_parser(
        "confirm",
        help="Ein Mensch bestaetigt EINEN Konsumenten -- probate ruft das nie fuer sich selbst auf",
    )
    c.add_argument("--entity", required=True, help="Der Konsument, der jetzt bestaetigt wird")
    c.add_argument("--evidence", required=True,
                    help="Warum wird bestaetigt -- Freitext von der Person, die bestaetigt, "
                         "nicht von probate erzeugt")
    c.add_argument("--campaign", default=str(CAMPAIGN_STATE), help="Pfad zur campaign.json aus 'apply'")
    c.add_argument("--gms", default=DEFAULT_GMS)
    c.add_argument("--token", default=None, help="Personal Access Token; sonst DATAHUB_TOKEN aus der Umgebung")

    sub.add_parser("status", help="Stand der laufenden Abloesung")
    r = sub.add_parser("revert", help="alle journalisierten Schreibvorgaenge zuruecknehmen")
    r.add_argument("--gms", default=DEFAULT_GMS)
    r.add_argument("--token", default=None, help="Personal Access Token; sonst DATAHUB_TOKEN aus der Umgebung")

    lg = sub.add_parser("ledger", help="Kanten-Register: deklarierte Lineage gegen gemessene Nutzung")
    lg.add_argument("--focus", required=True, help="Dataset-URN, dessen Kanten geprueft werden")
    lg.add_argument("--gms", default=DEFAULT_GMS)
    lg.add_argument("--token", default=None, help="Personal Access Token; sonst DATAHUB_TOKEN aus der Umgebung")
    lg.add_argument("--lineage-count", dest="lineage_count", type=int, default=200,
                    help="Obergrenze der Lineage-Abfrage (Falle 12: >100'000 Zeichen ohne Vorgabe)")
    lg.add_argument("--now-ms", dest="now_ms", type=int, default=None,
                    help="Beobachtungszeitpunkt in ms; Vorgabe ist jetzt. Nur eine SICHT, "
                         "veraendert keine Daten -- traegt den Knopf 'Zeit vorspulen'")
    lg.add_argument("--out", default="harness/runs/ledger.json")
    lg.add_argument("--judge", action="store_true",
                    help="Modell-Urteil ueber auffaellige Kanten (einziger Modellaufruf im Projekt)")
    lg.add_argument("--judge-limit", dest="judge_limit", type=int, default=20,
                    help="Obergrenze der Kanten, die dem Modell vorgelegt werden")

    args = p.parse_args()

    if args.cmd == "start":
        gms = Gms(args.gms, token=args.token)
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
        gms = Gms(args.gms, token=args.token)
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
            "form_urn": None,
            "prompt_id": None,
            "property_urn": "urn:li:structuredProperty:probate_migrated",
            "awaiting_confirmation": [],
            "signed": [],
            "signed_count": 0,
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
            CAMPAIGN_STATE.write_text(json.dumps(result, indent=2), encoding="utf-8")
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

        # WICHTIG (Live-Fund 2026-08-06, korrigiert): apply() schlaegt vor,
        # es signiert nicht. probate wuerde sonst sich selbst zum Owner des
        # Konsumenten machen und die eigene Unterschrift bestaetigen --
        # genau die Behauptung ohne Beleg, gegen die dieses Projekt
        # antritt. assign()/autofill() sind Vorschlag mit Beleg; verify()
        # ist ab hier ausschliesslich Sache von 'probate confirm', das ein
        # Mensch fuer JEDEN Konsumenten einzeln aufruft.
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
            result["form_urn"] = form_urn
            result["prompt_id"] = prompt_id
            result["awaiting_confirmation"] = live

        after_aspect = _rewrite_test_results(wb, args.predecessor, args.successor, live, [])

        Path("harness/runs").mkdir(parents=True, exist_ok=True)
        Path("harness/runs/testResults-vorher-nachher.json").write_text(
            json.dumps({"vorher": before_aspect, "nachher": after_aspect}, indent=2), encoding="utf-8"
        )
        CAMPAIGN_STATE.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        if live:
            print(f"\n{len(live)} Formular(e) warten auf Bestaetigung. probate signiert nicht "
                  f"fuer die Konsumenten -- lauf 'probate confirm --entity <urn> --evidence \"...\"' "
                  f"pro Konsument, nachdem ein Mensch geprueft hat.")
        return 0

    if args.cmd == "confirm":
        campaign_path = Path(args.campaign)
        if not campaign_path.exists():
            print(f"Keine Kampagne unter {campaign_path} -- erst 'probate apply' laufen lassen.")
            return 1
        state = json.loads(campaign_path.read_text(encoding="utf-8"))
        form_urn = state.get("form_urn")
        if not form_urn:
            print("Kampagne hat kein offenes Formular (kein lebender Konsument oder Beweis fehlgeschlagen).")
            return 1
        if args.entity not in state.get("awaiting_confirmation", []):
            print(f"{args.entity} steht nicht auf der Liste wartender Konsumenten dieser Kampagne.")
            return 1

        gms = Gms(args.gms, token=args.token)
        wb = Writeback(gms, dry_run=False, journal_path="harness/runs/journal.jsonl")
        evidence = {"note": args.evidence}
        r = verify(wb, form_urn, args.entity, evidence)
        if not r.applied:
            print("verifyForm nicht angewendet (dry-run oder Fehler).")
            return 1

        live = state.get("consumers", [])
        signed = _signed_count(gms, form_urn, live)
        after_aspect = _rewrite_test_results(wb, state["predecessor"], state["successor"], live, signed)

        state["signed"] = signed
        state["signed_count"] = len(signed)
        state["awaiting_confirmation"] = [c for c in live if c not in signed]
        campaign_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        Path("harness/runs/testResults-vorher-nachher.json").write_text(
            json.dumps({"nachher": after_aspect}, indent=2), encoding="utf-8"
        )
        print(f"{args.entity} bestaetigt. {len(signed)}/{len(live)} Konsumenten signiert.")
        return 0

    if args.cmd == "revert":
        n = Writeback(Gms(args.gms, token=args.token), dry_run=False).revert_all()
        print(f"{n} Schreibvorgaenge zurueckgenommen")
        return 0

    if args.cmd == "ledger":
        import time
        gms = Gms(args.gms, token=args.token)
        now_ms = args.now_ms if args.now_ms is not None else int(time.time() * 1000)
        # --judge ist die einzige Stelle im Projekt, die claude_cli_transport
        # erzeugt -- ohne den Schalter bleibt judge_transport None und
        # ledger_run() laesst den Urteils-Zweig komplett aus (s. ledger.run()
        # Docstring: "AUS, solange judge_transport None bleibt").
        transport = None
        if args.judge:
            from probate.judge import claude_cli_transport
            transport = claude_cli_transport()
        # ledger_run() wirft GmsError bei jedem fehlgeschlagenen Fetch, BEVOR
        # hier je ein write_text passiert -- ein Fehlschlag mitten im Lauf
        # hinterlaesst also gar kein Artefakt statt eines unvollstaendigen,
        # das Vollstaendigkeit behaupten wuerde (global-constraints.md).
        out = ledger_run(gms, args.focus, now_ms, lineage_count=args.lineage_count,
                         judge_transport=transport, judge_limit=args.judge_limit)
        out["gms"] = args.gms
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
        # "judgements" ist wie "edges" eine Liste pro Kante -- fuer die
        # Konsole zaehlt die Zusammenfassung (judged_edges/judged_with_model/
        # judged_fallback/judge_seconds_total stehen bereits flach in `out`),
        # die Details liegen in der geschriebenen Datei.
        summary = {k: v for k, v in out.items() if k not in ("edges", "judgements")}
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        if out["coverage_thin"]:
            print("\n  ACHTUNG duenne Abdeckung: "
                  f"{out['coverage_buckets_seen']} Zeitfenster insgesamt. "
                  f"{out['edges_unknown']} Kante(n) sind 'unknown', NICHT 'dead'.")
        return 0

    print(CAMPAIGN_STATE.read_text(encoding="utf-8"))
    return 0
