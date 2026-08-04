"""Das Tor. Neun Mutations einzeln gegen die laufende Instanz.

Vorhandensein im GraphQL-Schema ist KEIN Beweis fuer Ausfuehrbarkeit.
Gemessen 2026-08-04: ein v3-REST-Schreibversuch lieferte HTTP 200 und
schrieb nichts, weil der Endpunkt eine Liste erwartet und ein Objekt bekam.

Instanz: http://localhost:28080 (NICHT 18080 wie urspruenglich im Plan -
18080 traegt showcase-ecommerce, gegen das ein anderes Projekt bereits
veroeffentlichte Zahlen erhoben hat; 28080 laeuft auf derselben Version
v1.5.0.6, serverEnv core - das Ergebnis ueberträgt sich unveraendert).
Port 8080 wird unter keinen Umstaenden angefasst - dort laeuft eine
WhatsApp-Bridge.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from dataclasses import dataclass
from typing import Callable

GMS = "http://localhost:28080"
STAMP = {"time": 1754300000000, "actor": "urn:li:corpuser:datahub"}
DS_A = "urn:li:dataset:(urn:li:dataPlatform:snowflake,probate.probe_v1,PROD)"
DS_B = "urn:li:dataset:(urn:li:dataPlatform:snowflake,probate.probe_v2,PROD)"


@dataclass
class ProbeResult:
    name: str
    ok: bool
    detail: str


def summarise(results: list[ProbeResult]) -> dict:
    failed = [r.name for r in results if not r.ok]
    return {
        "total": len(results),
        "ok": len(results) - len(failed),
        "failed": failed,
        "gate_passed": not failed,
    }


def _post(path: str, payload: dict) -> tuple[int, object]:
    req = urllib.request.Request(
        f"{GMS}{path}", data=json.dumps(payload).encode(), method="POST"
    )
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else None)
    except Exception as exc:  # noqa: BLE001 - der Fehlerfall MUSS laut werden
        return 0, f"{type(exc).__name__}: {exc}"


def _gql(query: str) -> tuple[bool, str]:
    """GraphQL. Ein 'errors'-Feld ist ein Fehlschlag, auch bei HTTP 200."""
    status, body = _post("/api/graphql", {"query": query})
    if status != 200 or not isinstance(body, dict):
        return False, f"HTTP {status} {str(body)[:120]}"
    if body.get("errors"):
        return False, json.dumps(body["errors"])[:160]
    return True, json.dumps(body.get("data"))[:120]


MUTATIONS: dict[str, str] = {
    "upsertCustomAssertion": f'''mutation {{ upsertCustomAssertion(
        urn: "urn:li:assertion:probate-probe",
        input: {{ entityUrn: "{DS_B}", type: "PARITY",
                  description: "probate preflight probe",
                  platform: {{ urn: "urn:li:dataPlatform:snowflake" }} }}
      ) {{ urn }} }}''',
    "reportAssertionResult": '''mutation { reportAssertionResult(
        urn: "urn:li:assertion:probate-probe",
        result: { timestampMillis: 1754300000000, type: SUCCESS }
      ) }''',
    "upsertDataContract": f'''mutation {{ upsertDataContract(
        urn: "urn:li:dataContract:probate-probe",
        input: {{ entityUrn: "{DS_B}",
                  dataQuality: [{{ assertionUrn: "urn:li:assertion:probate-probe" }}] }}
      ) {{ urn }} }}''',
    "linkAssetVersion": f'''mutation {{ linkAssetVersion(
        input: {{ versionSet: "urn:li:versionSet:(probate-probe,dataset)",
                  linkedEntity: "{DS_B}", version: "v2" }}
      ) {{ urn }} }}''',
    "raiseIncident": f'''mutation {{ raiseIncident(
        input: {{ resourceUrn: "{DS_A}", type: OPERATIONAL,
                  title: "probate preflight probe",
                  description: "probe" }}
      ) }}''',
    "createForm": '''mutation { createForm(input: {
        id: "probate-probe", name: "Probate probe", type: VERIFICATION,
        prompts: [] }) { urn } }''',
    "batchAssignForm": f'''mutation {{ batchAssignForm(input: {{
        formUrn: "urn:li:form:probate-probe",
        entityUrns: ["{DS_A}"] }}) }}''',
    # Formfehler korrigiert 2026-08-04: submitFormPrompt liefert ein
    # nacktes Boolean zurueck, keine Subselection moeglich. Original hatte
    # `{ success }` -> GraphQL-Schemafehler SubselectionNotAllowed.
    "submitFormPrompt": f'''mutation {{ submitFormPrompt(
        urn: "{DS_A}",
        input: {{ formUrn: "urn:li:form:probate-probe",
                  promptId: "p1", type: STRUCTURED_PROPERTY }}
      ) }}''',
    "verifyForm": f'''mutation {{ verifyForm(input: {{
        formUrn: "urn:li:form:probate-probe", entityUrn: "{DS_A}" }}) }}''',
}


def seed_datasets() -> ProbeResult:
    """Zwei echte Datasets, damit die Mutations etwas zum Anfassen haben.

    LISTE, nicht Objekt - das ist die Falle.
    """
    payload = [
        {"urn": urn, "datasetProperties": {"value": {"name": name}}}
        for urn, name in ((DS_A, "probe_v1"), (DS_B, "probe_v2"))
    ]
    status, body = _post("/openapi/v3/entity/dataset?async=false", payload)
    ok = status == 200 and isinstance(body, list) and len(body) == 2
    return ProbeResult("seed_datasets", ok, f"HTTP {status}, {len(body) if isinstance(body, list) else 0} geschrieben")


def run_all() -> list[ProbeResult]:
    results = [seed_datasets()]
    for name, query in MUTATIONS.items():
        ok, detail = _gql(query)
        results.append(ProbeResult(name, ok, detail))
    return results


def main() -> int:
    results = run_all()
    for r in results:
        print(f"  {'OK  ' if r.ok else 'FEHL'}  {r.name:<26} {r.detail}")
    s = summarise(results)
    print(f"\n  {s['ok']}/{s['total']} erfolgreich")
    if not s["gate_passed"]:
        print(f"  TOR GESCHLOSSEN - gescheitert: {', '.join(s['failed'])}")
        print("  Die Spezifikation muss angepasst werden, BEVOR gebaut wird.")
        return 1
    print("  TOR OFFEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
