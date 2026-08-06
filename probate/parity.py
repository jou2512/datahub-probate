"""Der Beweis. Ohne ihn schaltet Probate nicht um.

Enthaltung ist ein Ergebnis: fehlende Zaehlbelege ergeben KEIN 'ok',
sondern ein begruendetes Nein.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ROW_TOLERANCE = 0.01


@dataclass(frozen=True)
class SchemaDiff:
    missing: list[str]
    added: list[str]
    type_changed: list[tuple[str, str, str]]


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reasons: list[str]
    evidence: dict = field(default_factory=dict)


def compare_schemas(old: list[dict], new: list[dict]) -> SchemaDiff:
    o = {f["fieldPath"]: f.get("type") for f in old}
    n = {f["fieldPath"]: f.get("type") for f in new}
    return SchemaDiff(
        missing=sorted(set(o) - set(n)),
        added=sorted(set(n) - set(o)),
        type_changed=sorted(
            (p, o[p], n[p]) for p in set(o) & set(n) if o[p] != n[p]
        ),
    )


def verdict(diff: SchemaDiff, counts: dict) -> Verdict:
    reasons: list[str] = []

    for col in diff.missing:
        reasons.append(f"Spalte fehlt im Nachfolger: {col}")
    for col, old_t, new_t in diff.type_changed:
        reasons.append(f"Typ geaendert: {col} {old_t} -> {new_t}")

    if "old" not in counts or "new" not in counts:
        reasons.append("Zeilenzahl unbekannt - kein Beleg, also kein Freibrief")
    else:
        old_n, new_n = counts["old"], counts["new"]
        if old_n == 0 and new_n == 0:
            pass
        else:
            gap = abs(old_n - new_n) / max(old_n, 1)
            if gap > ROW_TOLERANCE:
                reasons.append(
                    f"Zeilenzahl weicht um {gap:.1%} ab ({old_n} -> {new_n}), "
                    f"erlaubt sind {ROW_TOLERANCE:.0%}"
                )

    return Verdict(
        ok=not reasons,
        reasons=reasons,
        evidence={
            "counts": counts,
            "missing": diff.missing,
            "added": diff.added,
            "type_changed": diff.type_changed,
        },
    )


def assertion_payload(target_urn: str, v: Verdict) -> dict:
    """Nutzlast fuer upsertCustomAssertion + reportAssertionResult."""
    return {
        "entityUrn": target_urn,
        "type": "PARITY",
        "description": "Probate: Gleichwertigkeit des Nachfolgers",
        "result": "SUCCESS" if v.ok else "FAILURE",
        "properties": [
            {"key": "reasons", "value": "; ".join(v.reasons) or "keine"},
            {"key": "evidence", "value": str(v.evidence)[:900]},
        ],
    }
