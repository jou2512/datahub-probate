"""Die Nachfolge festschreiben - aber nur gegen Beweis.

Reihenfolge ist Absicht: erst die Zusage uebertragen, dann die Versionen
verbinden, dann erst den Vorgaenger abkuendigen. Wer zuerst abkuendigt,
hat einen Moment, in dem weder alt noch neu die Zusage traegt.
"""

from __future__ import annotations

import hashlib

from probate.parity import Verdict


class RefusedError(RuntimeError):
    """Probate schaltet ohne Beweis nicht um."""


def _contract_q(successor: str, assertion_urns: list[str]) -> str:
    quality = ", ".join(f'{{ assertionUrn: "{u}" }}' for u in assertion_urns)
    return f'''mutation {{ upsertDataContract(
        input: {{ entityUrn: "{successor}", dataQuality: [{quality}] }}
      ) {{ urn }} }}'''


def _version_q(version_set: str, successor: str) -> str:
    return f'''mutation {{ linkAssetVersion(
        input: {{ versionSet: "{version_set}", linkedEntity: "{successor}", version: "v2" }}
      ) {{ urn }} }}'''


def succeed(
    wb,
    predecessor: str,
    successor: str,
    verdict: Verdict,
    assertion_urns: list[str],
) -> dict:
    if not verdict.ok:
        raise RefusedError(
            "Keine Umschaltung ohne Beweis. Gruende: " + "; ".join(verdict.reasons)
        )

    # Live-Fund (2026-08-06): Pythons eingebautes hash() ist fuer str NICHT
    # stabil ueber Prozesslaeufe (PYTHONHASHSEED-Randomisierung, Standard
    # seit Py3.3) -- derselbe predecessor haette bei jedem Lauf eine andere
    # VersionSet-URN erzeugt, verwaiste VersionSets waeren die Folge.
    # hashlib.sha1 ist deterministisch.
    slug = hashlib.sha1(predecessor.encode()).hexdigest()[:12]
    version_set = f"urn:li:versionSet:(probate-{slug},dataset)"
    note = (
        f"Abgeloest durch {successor}. Gleichwertigkeit belegt durch "
        f"{', '.join(assertion_urns)}. Durchgefuehrt von Probate."
    )

    wb.mutation("upsertDataContract", _contract_q(successor, assertion_urns))
    wb.mutation("linkAssetVersion", _version_q(version_set, successor))
    wb.aspect(
        "dataset",
        predecessor,
        "deprecation",
        {
            "deprecated": True,
            "note": note,
            # Live gemessen (2026-08-06): probate authentifiziert ohne Token als
            # urn:li:corpuser:__datahub_system (per Gms().graphql("{ me { ... } }")).
            # "urn:li:corpuser:datahub" hier zu schreiben waere eine falsche
            # Zuschreibung, wer den Schreibvorgang tatsaechlich ausgefuehrt hat.
            "actor": "urn:li:corpuser:__datahub_system",
            # Deprecation.replacement (Quelle gelesen: Deprecation.pdl,
            # github.com/datahub-project/datahub) ist genau fuer diesen Zweck da --
            # ein strukturierter, abfragbarer Verweis statt nur Text im note-Feld.
            # decommissionTime bewusst weggelassen (optional, kein echter
            # Zeitpunkt bekannt) statt eines erfundenen None-Werts.
            "replacement": successor,
        },
    )
    return {"version_set": version_set, "deprecation_note": note}
