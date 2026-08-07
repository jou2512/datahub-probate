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


def test_correct_remove_edge_without_confirm_is_also_a_dry_run(tmp_path, monkeypatch, capsys):
    """remove_edge ist der einzige destruktive, nicht-additive Pfad -- sein
    dry-run-Verhalten war bisher nur strukturell ueber das geteilte
    Writeback-Gate mitgedeckt, nie direkt gepinnt (Review-Nachtrag).
    Kein --confirm -> kein Schreibvorgang, exakt wie bei add_edge."""
    existing = {("dataset", "urn:down", "upstreamLineage"): {"value": {"upstreams": [
        {"dataset": "urn:a", "type": "TRANSFORMED", "auditStamp": {"time": 1, "actor": "x"}},
    ]}}}
    fake = _patch_gms(monkeypatch, existing)

    rc = _run(monkeypatch, ["correct", "--edge", "urn:a->urn:down", "--kind", "remove_edge"])

    assert rc == 1
    assert fake.upserts == []
    assert "DRY-RUN" in capsys.readouterr().out


# --- Review-Nachtrag (07.08.): 'revert' unterscheidet ein FEHLENDES Journal
# nicht von einem VORHANDENEN, leeren -- beide gaben bislang identisch
# "0 Schreibvorgaenge zurueckgenommen", Exit 0 zurueck. Ein Tippfehler im
# Pfad oder ein bares 'probate revert' nach 'correct --journal <anderer-
# pfad>' sieht dann aus wie "nichts stand aus", waehrend ein echter
# Schreibvorgang live bleibt -- genau die Verwechslung, gegen die dieses
# Projekt antritt. writeback.py ist gesperrt; die Unterscheidung passiert
# in cli.py, VOR dem Aufruf von revert_all().

def test_revert_refuses_when_the_journal_file_does_not_exist_at_all(tmp_path, monkeypatch, capsys):
    _patch_gms(monkeypatch)
    missing = tmp_path / "nie-geschrieben.jsonl"

    rc = _run(monkeypatch, ["revert", "--journal", str(missing)])

    assert rc == 1  # NICHT 0 -- das waere ununterscheidbar von "0 eintraege, alles gut"
    out = capsys.readouterr().out
    assert "KEIN Journal" in out
    assert str(missing) in out


def test_revert_on_an_existing_but_empty_journal_still_reports_zero_and_succeeds(tmp_path, monkeypatch, capsys):
    """Der Gegenfall zum Fund oben: ein Journal, das WIRKLICH existiert und
    WIRKLICH leer ist, bleibt der legitime Erfolgsfall (Exit 0) -- die
    Unterscheidung ist 'existiert die Datei', nicht 'ist sie leer'."""
    _patch_gms(monkeypatch)
    empty = tmp_path / "leer.jsonl"
    empty.write_text("", encoding="utf-8")

    rc = _run(monkeypatch, ["revert", "--journal", str(empty)])

    assert rc == 0
    assert "0 Schreibvorgaenge zurueckgenommen" in capsys.readouterr().out


def test_correct_confirm_on_a_non_default_journal_warns_with_the_exact_revert_command(tmp_path, monkeypatch, capsys):
    """Ohne diese Warnung waere ein Schreibvorgang unter --journal live und
    NUR ueber denselben Pfad revertierbar, ohne dass irgendetwas das dem
    Menschen sagt (Review-Nachtrag)."""
    proposals_path = tmp_path / "proposals.json"
    _write_proposals(proposals_path, [ADD_EDGE_PROPOSAL])
    _patch_gms(monkeypatch)
    monkeypatch.chdir(tmp_path)
    custom_journal = tmp_path / "mein-lauf.jsonl"

    rc = _run(monkeypatch, ["correct", "--edge", "urn:up->urn:down", "--kind", "add_edge",
                             "--proposals", str(proposals_path), "--confirm",
                             "--journal", str(custom_journal)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "ACHTUNG" in out
    assert f'probate revert --journal "{custom_journal}"' in out


def test_correct_confirm_on_the_default_journal_does_not_warn(tmp_path, monkeypatch, capsys):
    """Gegenprobe: die Warnung ist an den NICHT-Standard-Pfad gebunden, kein
    Rauschen bei jedem normalen Aufruf."""
    proposals_path = tmp_path / "proposals.json"
    _write_proposals(proposals_path, [ADD_EDGE_PROPOSAL])
    _patch_gms(monkeypatch)
    monkeypatch.chdir(tmp_path)

    rc = _run(monkeypatch, ["correct", "--edge", "urn:up->urn:down", "--kind", "add_edge",
                             "--proposals", str(proposals_path), "--confirm"])

    assert rc == 0
    assert "ACHTUNG" not in capsys.readouterr().out
