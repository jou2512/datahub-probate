"""Query-Log erzeugen, damit 'gemessene Nutzung' ueberhaupt eine Quelle hat.

showcase-ecommerce liefert 0 Query-Entitaeten (gemessen 2026-08-04).
"""

from __future__ import annotations

import hashlib

from probate.gms import Gms

STAMP = {"time": 1754300000000, "actor": "urn:li:corpuser:datahub"}


def build_query_records(pairs: list[tuple[str, str]]) -> list[dict]:
    records = []
    for sql, dataset_urn in pairs:
        qid = hashlib.sha1(sql.encode()).hexdigest()[:16]
        records.append(
            {
                "urn": f"urn:li:query:{qid}",
                "queryProperties": {
                    "value": {
                        "statement": {"value": sql, "language": "SQL"},
                        "source": "MANUAL",
                        "created": STAMP,
                        "lastModified": STAMP,
                    }
                },
                "querySubjects": {"value": {"subjects": [{"entity": dataset_urn}]}},
            }
        )
    return records


def seed(pairs: list[tuple[str, str]], gms: Gms | None = None) -> int:
    gms = gms or Gms()
    written = gms.upsert("query", build_query_records(pairs))
    return len(written)
