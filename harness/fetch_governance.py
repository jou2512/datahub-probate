"""Domaene und Besitzer je Tabelle -- aus dem Katalog GEMESSEN, nicht geraten.

WARUM diese Datei existiert: `docs/werkbank-spec.md`, Bereich 2, verlangt in
der Filterzeile eine Auswahlliste **Domaene** und eine **Besitzer**. Beide
Angaben liegen im Katalog (der Demo-Seed schreibt `domains` und `ownership`
auf die Tabellen), aber sie stehen NICHT im Lauf-Artefakt: ein Register-Lauf
misst Kanten, nicht Governance.

Zwei Wege waeren falsch gewesen:

  * Die Domaene aus dem Datenbanknamen ABLEITEN. `probate_demo_finance` sieht
    aus wie die Domaene "Finance", und in diesem Seed stimmt das sogar --
    aber es ist geraten, nicht gelesen. In einem echten Katalog ist die
    Domaene eine eigene Entitaet, die mit dem Namensschema nichts zu tun
    haben muss. Ein Filter, der eine Namenskonvention als Governance
    ausgibt, ist genau die Behauptung ohne Beleg, gegen die dieses Projekt
    antritt.
  * Die Werte im Browser oder in der Konsole HARTKODIEREN. Die Spec sagt
    woertlich "Auswahlliste aus den Daten, nicht hartkodiert".

Also: einmal messen, als Artefakt hinlegen, und die Konsole liest das
Artefakt. Der Nebeneffekt ist der wichtigere -- das Artefakt sagt selbst,
WAS es nachgeschlagen hat. Damit kann die Oberflaeche die Null-Regel
einhalten:

    Tabelle steht im Artefakt, `domain` ist `null`   -> "keine Domaene"  (gemessene Abwesenheit)
    Tabelle steht GAR NICHT im Artefakt              -> "nicht nachgeschlagen"
    Artefakt fehlt ganz                              -> Filter wird gar nicht angeboten

Diese drei Faelle sehen in der Konsole verschieden aus. Ein einzelner
Ruecklauf "unbekannt" fuer alle drei waere derselbe Fehler wie ein leerer
Balken, wo nie gemessen wurde.

Aufruf:
    uv run --python 3.11 python -m harness.fetch_governance
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Keine f-String-GraphQL (Sicherheits-Checkliste): jeder Wert geht als
# Variable, nie in den Abfragetext.
GOVERNANCE_Q = """
query($q: String!, $start: Int!, $count: Int!) {
  searchAcrossEntities(input: {types: [DATASET], query: $q, start: $start, count: $count}) {
    start
    count
    total
    searchResults {
      entity {
        urn
        ... on Dataset {
          domain { domain { urn properties { name } } }
          ownership {
            owners {
              owner { ... on CorpUser { urn } ... on CorpGroup { urn } }
              type
            }
          }
        }
      }
    }
  }
}
"""

DEFAULT_LEDGER = Path("harness/runs/demo-katalog-ledger.json")
DEFAULT_OUT = Path("harness/runs/demo-katalog-governance.json")
PAGE = 200


def ledger_urns(path: Path) -> list[str]:
    """Die Tabellen, um die es geht -- beide Enden jeder Kante des Registers.

    Der Katalog traegt tausende Datensaetze; nachgeschlagen wird nur, was in
    der Konsole ueberhaupt als Zeile erscheinen kann. Alles andere waere ein
    Artefakt, das groesser ist als seine Frage.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    urns: set[str] = set()
    for edge in data.get("edges") or []:
        for side in ("upstream", "downstream"):
            if edge.get(side):
                urns.add(edge[side])
    return sorted(urns)


def owner_name(urn: str) -> str:
    """Der Anzeigename eines Besitzers: der letzte URN-Abschnitt.

    Bewusst KEINE erfundene Klarschrift ("m.keller" -> "M. Keller"): der
    Katalog liefert fuer diese Nutzer keine `properties.displayName` (live
    geprueft, alle `null`), und aus einem Login einen Personennamen zu
    basteln waere eine Behauptung ueber einen Menschen.
    """
    return urn.rsplit(":", 1)[-1] if urn else ""


def collect(gms, wanted: set[str], page: int = PAGE) -> dict:
    """Der Sweep ueber den Katalog. Gibt zurueck, was gefunden wurde -- und
    wie viel ueberhaupt angesehen wurde."""
    found: dict[str, dict] = {}
    scanned = 0
    total = None
    start = 0
    while True:
        res = (gms.graphql(GOVERNANCE_Q, {"q": "*", "start": start, "count": page})
               .get("searchAcrossEntities") or {})
        rows = res.get("searchResults") or []
        if total is None:
            total = int(res.get("total") or 0)
        if not rows:
            break
        for hit in rows:
            ent = hit.get("entity") or {}
            urn = ent.get("urn") or ""
            scanned += 1
            if urn not in wanted:
                continue
            dom = ((ent.get("domain") or {}).get("domain")) or {}
            owners = []
            for o in ((ent.get("ownership") or {}).get("owners") or []):
                ourn = ((o.get("owner") or {}).get("urn")) or ""
                if ourn:
                    owners.append({"urn": ourn, "name": owner_name(ourn),
                                   "type": o.get("type") or ""})
            found[urn] = {
                "domain": dom.get("urn") or None,
                "domain_name": ((dom.get("properties") or {}).get("name")) or None,
                "owners": owners,
            }
        start += len(rows)
        if total is not None and start >= total:
            break
    return {"tables": found, "scanned": scanned, "catalog_total": total or 0}


def tally(tables: dict) -> tuple[list[dict], list[dict]]:
    """Domaenen und Besitzer mit ihrer Tabellen-Anzahl.

    Das ist die Anzahl der TABELLEN, nicht der Kanten -- die kantenbezogene
    Zahl fuer die Auswahlliste rechnet `ui/console_api.py`, weil nur die
    Konsole weiss, welches Register gerade gezeigt wird.
    """
    doms: dict[str, dict] = {}
    owns: dict[str, dict] = {}
    for info in tables.values():
        d = info.get("domain")
        if d:
            row = doms.setdefault(d, {"urn": d, "name": info.get("domain_name") or d,
                                      "tables": 0})
            row["tables"] += 1
        for o in info.get("owners") or []:
            row = owns.setdefault(o["urn"], {"urn": o["urn"], "name": o["name"],
                                             "tables": 0})
            row["tables"] += 1
    return (sorted(doms.values(), key=lambda r: (-r["tables"], r["name"])),
            sorted(owns.values(), key=lambda r: (-r["tables"], r["name"])))


def run(gms, ledger: Path, out: Path) -> dict:
    wanted = set(ledger_urns(ledger))
    t0 = time.time()
    got = collect(gms, wanted)
    tables = got["tables"]
    domains, owners = tally(tables)
    missing = sorted(wanted - set(tables))
    payload = {
        "generated_at_ms": int(time.time() * 1000),
        "generated_at_iso": datetime.now(tz=timezone.utc).isoformat(),
        "source_ledger": str(ledger).replace("\\", "/"),
        "seconds": round(time.time() - t0, 2),
        "catalog_datasets_total": got["catalog_total"],
        "catalog_datasets_scanned": got["scanned"],
        "tables_wanted": len(wanted),
        "tables_looked_up": len(tables),
        # Die drei Zahlen, die die Null-Regel tragen: nachgeschlagen, davon
        # mit Domaene, davon mit Besitzer. Wer nur "mit Domaene" meldet,
        # kann "keine Domaene" nicht von "nie nachgesehen" unterscheiden.
        "tables_with_domain": sum(1 for t in tables.values() if t.get("domain")),
        "tables_with_owner": sum(1 for t in tables.values() if t.get("owners")),
        "tables_not_found": missing,
        "domains_total": len(domains),
        "owners_total": len(owners),
        "domains": domains,
        "owners": owners,
        "tables": tables,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    return payload


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gms", default="http://localhost:28080")
    ap.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)

    from probate.gms import Gms

    payload = run(Gms(args.gms), Path(args.ledger), Path(args.out))
    print(f"{payload['tables_looked_up']} von {payload['tables_wanted']} Tabellen "
          f"nachgeschlagen ({payload['catalog_datasets_scanned']} Datensaetze gesichtet, "
          f"{payload['seconds']}s)")
    print(f"  {payload['tables_with_domain']} mit Domaene ({payload['domains_total']} Domaenen), "
          f"{payload['tables_with_owner']} mit Besitzer ({payload['owners_total']} Besitzer)")
    if payload["tables_not_found"]:
        print(f"  {len(payload['tables_not_found'])} Tabellen NICHT gefunden -- "
              f"sie erscheinen als 'nicht nachgeschlagen', nie als 'keine Domaene'")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
