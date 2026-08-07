"""CLI-Verdrahtung von Task 14: `probate propose` und `probate correct`.

Warum diese Datei existiert: `probate/correct.py` ist selbst schon
vollstaendig getestet (`tests/test_correct.py`) -- diese Datei prueft NICHT
die Korrektur-Logik noch einmal, sondern nur die duenne CLI-Schicht darum:
Argumente parsen, das richtige Artefakt lesen/schreiben, die drei
Ausgaenge (geschrieben / dry-run / Enthaltung) unterscheiden, und dass ein
blosser `correct`-Aufruf ohne `--confirm` strukturell nicht schreiben kann.

Handgeschriebener Fake wie `tests/test_writeback.py::FakeGms` -- kein
Mock-Rahmenwerk (global-constraints.md). `probate.cli.Gms` wird per
monkeypatch durch eine Fabrikfunktion ersetzt, die immer denselben Fake
zurueckgibt -- so bleibt `Gms(args.gms, token=args.token)` im
Produktionscode unveraendert, der Test spricht trotzdem nie ein echtes GMS
an.
"""

from __future__ import annotations

import json

import probate.cli as cli


class FakeGms:
    """Wie tests/test_writeback.py::FakeGms, plus `.base` (correct.py
    braucht `wb.gms.get_aspect`, nicht `.base` -- hier trotzdem vorhanden,
    falls ein Aufrufer es je liest)."""

    def __init__(self, existing=None):
        self.existing = existing or {}
        self.upserts = []
        self.deletes = []
        self.base = "http://fake-gms.invalid"

    def get_aspect(self, entity_type, urn, aspect):
        return self.existing.get((entity_type, urn, aspect))

    def upsert(self, entity_type, records, sync=True):
        self.upserts.append((entity_type, records))
        return records

    def delete_aspect(self, entity_type, urn, aspect):
        self.deletes.append((entity_type, urn, aspect))


def _patch_gms(monkeypatch, existing=None):
    fake = FakeGms(existing)
    monkeypatch.setattr(cli, "Gms", lambda base=None, token=None: fake)
    return fake


def _run(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["probate", *argv])
    return cli.main()


# --- propose -- schreibt nichts in den Katalog ---------------------------

LEDGER_FIXTURE = {
    "focus": "urn:up",
    "seeded": True,
    "edges": [
        {"edge": "urn:up->urn:m", "state": "missing", "upstream": "urn:up",
         "downstream": "urn:m",
         "evidence": {"query_urns": ["urn:li:query:q1"], "cooccurrence_count": 1,
                      "direction_evidence": "co-occurrence (undirected)"},
         "timeline": {}},
        {"edge": "urn:up->urn:u", "state": "unknown", "upstream": "urn:up",
         "downstream": "urn:u", "evidence": {"reason": "keine Nutzungs-Zeitfenster"},
         "timeline": {}},
    ],
}


def test_propose_writes_a_proposal_per_non_unknown_edge_and_skips_unknown(tmp_path, monkeypatch, capsys):
    ledger_path = tmp_path / "ledger.json"
    out_path = tmp_path / "proposals.json"
    ledger_path.write_text(json.dumps(LEDGER_FIXTURE), encoding="utf-8")

    rc = _run(monkeypatch, ["propose", "--ledger", str(ledger_path), "--out", str(out_path)])

    assert rc == 0
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["seeded"] is True
    assert len(written["proposals"]) == 1
    assert written["proposals"][0]["kind"] == "add_edge"
    assert written["proposals"][0]["edge"] == "urn:up->urn:m"
    assert not any(p["edge"] == "urn:up->urn:u" for p in written["proposals"])
    out = capsys.readouterr().out
    assert "add_edge" in out
    assert "1 Vorschlag" in out  # menschlich lesbare Zusammenfassung


def test_propose_refuses_when_the_ledger_file_is_missing(tmp_path, monkeypatch):
    rc = _run(monkeypatch, ["propose", "--ledger", str(tmp_path / "nichts.json"),
                             "--out", str(tmp_path / "out.json")])
    assert rc == 1
    assert not (tmp_path / "out.json").exists()


# --- correct -- Vorgabe ist dry-run, schreibt nur mit --confirm ----------

def _write_proposals(path, proposals):
    path.write_text(json.dumps({"seeded": True, "proposals": proposals}), encoding="utf-8")


ADD_EDGE_PROPOSAL = {
    "kind": "add_edge", "edge": "urn:up->urn:down", "target_urn": "urn:down",
    "aspect": "upstreamLineage", "state": "missing",
    "evidence": {"query_urns": ["urn:li:query:q1"], "cooccurrence_count": 1,
                 "direction_evidence": "co-occurrence (undirected)"},
    "human_summary": "test-vorschlag",
}


def test_correct_without_confirm_is_a_dry_run_and_writes_nothing(tmp_path, monkeypatch, capsys):
    proposals_path = tmp_path / "proposals.json"
    _write_proposals(proposals_path, [ADD_EDGE_PROPOSAL])
    fake = _patch_gms(monkeypatch)

    rc = _run(monkeypatch, ["correct", "--edge", "urn:up->urn:down", "--kind", "add_edge",
                             "--proposals", str(proposals_path)])

    assert rc == 1
    assert fake.upserts == []  # der eigentliche Beweis: kein Schreibvorgang
    assert "DRY-RUN" in capsys.readouterr().out


def test_correct_with_confirm_writes_through_writeback(tmp_path, monkeypatch, capsys):
    proposals_path = tmp_path / "proposals.json"
    _write_proposals(proposals_path, [ADD_EDGE_PROPOSAL])
    fake = _patch_gms(monkeypatch)
    monkeypatch.chdir(tmp_path)  # journal.jsonl landet isoliert, nicht im echten Projekt

    rc = _run(monkeypatch, ["correct", "--edge", "urn:up->urn:down", "--kind", "add_edge",
                             "--proposals", str(proposals_path), "--confirm"])

    assert rc == 0
    assert len(fake.upserts) == 1
    entity_type, records = fake.upserts[0]
    assert entity_type == "dataset"
    assert records[0]["urn"] == "urn:down"
    upstreams = records[0]["upstreamLineage"]["value"]["upstreams"]
    assert "urn:up" in {u["dataset"] for u in upstreams}
    assert "GESCHRIEBEN" in capsys.readouterr().out


def test_correct_reports_an_abstention_as_neither_error_nor_success(tmp_path, monkeypatch, capsys):
    """Die Kennzahl dieses Produkts: ein fehlendes Messdatum ist eine
    Enthaltung, kein Fehler und kein stiller Erfolg -- eigener
    Rueckgabewert (3), eigene Meldung."""
    proposal = {
        "kind": "mark_dead", "edge": "urn:up->urn:down", "target_urn": "urn:down",
        "aspect": "upstreamLineage", "state": "dead",
        "evidence": {"last_covered_ms": None, "dead_since_days": 40,
                     "dead_since_is_lower_bound": True, "buckets_checked": 5},
        "human_summary": "nur untergrenze",
    }
    proposals_path = tmp_path / "proposals.json"
    _write_proposals(proposals_path, [proposal])
    fake = _patch_gms(monkeypatch)

    rc = _run(monkeypatch, ["correct", "--edge", "urn:up->urn:down", "--kind", "mark_dead",
                             "--proposals", str(proposals_path), "--confirm"])

    assert rc == 3
    assert fake.upserts == []
    assert "ENTHALTUNG" in capsys.readouterr().out


def test_correct_refuses_a_vacuous_proposal_loudly(tmp_path, monkeypatch, capsys):
    proposal = {**ADD_EDGE_PROPOSAL, "evidence": {}}
    proposals_path = tmp_path / "proposals.json"
    _write_proposals(proposals_path, [proposal])
    fake = _patch_gms(monkeypatch)

    rc = _run(monkeypatch, ["correct", "--edge", "urn:up->urn:down", "--kind", "add_edge",
                             "--proposals", str(proposals_path), "--confirm"])

    assert rc == 1
    assert fake.upserts == []
    assert "ABGELEHNT" in capsys.readouterr().out


def test_correct_reports_when_no_matching_proposal_exists(tmp_path, monkeypatch):
    proposals_path = tmp_path / "proposals.json"
    _write_proposals(proposals_path, [ADD_EDGE_PROPOSAL])
    _patch_gms(monkeypatch)

    rc = _run(monkeypatch, ["correct", "--edge", "urn:up->urn:andernorts", "--kind", "add_edge",
                             "--proposals", str(proposals_path), "--confirm"])
    assert rc == 1


def test_correct_reports_when_the_proposals_file_is_missing(tmp_path, monkeypatch):
    _patch_gms(monkeypatch)
    rc = _run(monkeypatch, ["correct", "--edge", "urn:up->urn:down", "--kind", "add_edge",
                             "--proposals", str(tmp_path / "nichts.json")])
    assert rc == 1


def test_correct_remove_edge_needs_no_proposals_file(tmp_path, monkeypatch):
    """remove_edge ist nicht additiv und kommt nie aus propose() -- der
    Mensch loest sie direkt aus, ohne ein Proposal-Artefakt."""
    existing = {("dataset", "urn:down", "upstreamLineage"): {"value": {"upstreams": [
        {"dataset": "urn:a", "type": "TRANSFORMED", "auditStamp": {"time": 1, "actor": "x"}},
        {"dataset": "urn:b", "type": "TRANSFORMED", "auditStamp": {"time": 1, "actor": "x"}},
    ]}}}
    fake = _patch_gms(monkeypatch, existing)
    monkeypatch.chdir(tmp_path)

    rc = _run(monkeypatch, ["correct", "--edge", "urn:a->urn:down", "--kind", "remove_edge", "--confirm"])

    assert rc == 0
    _, records = fake.upserts[0]
    upstreams = records[0]["upstreamLineage"]["value"]["upstreams"]
    assert [u["dataset"] for u in upstreams] == ["urn:b"]


def test_correct_remove_edge_rejects_a_malformed_edge_key(tmp_path, monkeypatch):
    _patch_gms(monkeypatch)
    rc = _run(monkeypatch, ["correct", "--edge", "kein-pfeil-hier", "--kind", "remove_edge", "--confirm"])
    assert rc == 1
