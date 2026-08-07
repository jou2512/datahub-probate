"""Der Uebergangs-Nachweis, ohne Netz.

Was hier geprueft wird, ist NICHT "wechselt eine Kante ihren Zustand" --
das ist eine Live-Messung und steht in `harness/runs/demo-transitions.json`.
Geprueft wird die Mechanik, die ein Live-Lauf still falsch machen koennte:

* dass `measure()` den Zustand aus dem Register liest und "die Kante gibt
  es in keiner Quelle" nicht als `unknown` verkleidet,
* dass `measure_until()` JEDE Messung behaelt (auch die, die noch nicht
  passte) -- sonst waere die Warteschleife ein Werkzeug, um so lange zu
  messen, bis das Ergebnis stimmt,
* dass die Ruecknahme NUR die eigenen Journal-Zeilen anfasst,
* dass die beiden Sperren (Mindestwartezeit, verbotene GMS-Ziele) wirklich
  abweisen statt zu warnen.
"""

import json

import pytest

import harness.demo_transitions as dt


class FakeGms:
    """Nur die vier Beruehrungspunkte, die `measure()` tatsaechlich nutzt.

    `usage_rows` ist eine Map URN -> Liste roher Zeitreihen-Zeilen; eine
    fehlende URN bedeutet "keine Nutzungsdaten", nicht "nicht gefragt" --
    der Unterschied ist im Test genauso wichtig wie im Produkt.
    """

    base = "http://localhost:28080"

    def __init__(self, lineage=(), query_urns=(), subjects=None, usage_rows=None):
        self.lineage = list(lineage)
        self.query_urns = list(query_urns)
        self.subjects = subjects or {}
        self.usage_rows = usage_rows or {}
        self.deleted: list[tuple] = []
        self.upserted: list[tuple] = []

    def graphql(self, query, variables=None):
        if "lineage(" in query:
            return {"dataset": {"lineage": {
                "relationships": [{"entity": {"urn": u}} for u in self.lineage]}}}
        return {"searchAcrossEntities": {
            "total": len(self.query_urns),
            "searchResults": [{"entity": {"urn": q}} for q in self.query_urns]}}

    def get_aspect(self, entity_type, urn, aspect):
        if entity_type == "query":
            subs = self.subjects.get(urn)
            return {"value": {"subjects": [{"entity": s} for s in subs]}} if subs else None
        return None

    def delete_aspect(self, entity_type, urn, aspect):
        self.deleted.append((entity_type, urn, aspect))

    def upsert(self, entity_type, records):
        self.upserted.append((entity_type, records))

    def _send(self, method, url, payload):
        rows = self.usage_rows.get(payload.get("urn"), [])
        inside = [r for r in rows
                  if payload["startTimeMillis"] <= r["timestampMillis"] <= payload["endTimeMillis"]]
        return 200, {"value": {"values": [{"aspect": {"value": json.dumps(r)}} for r in inside]}}


UP = "urn:li:dataset:(urn:li:dataPlatform:postgres,lab.up,PROD)"
DOWN = "urn:li:dataset:(urn:li:dataPlatform:postgres,lab.down,PROD)"
NOW = 1_786_000_000_000


def _bucket(ts, total=7):
    return {"timestampMillis": ts, "totalSqlQueries": total, "uniqueUserCount": 2,
            "eventGranularity": {"unit": "DAY", "multiple": 1}}


def test_measure_reads_the_state_from_the_ledger_not_from_a_button():
    """Deklariert + Paar-Abfrage + Nutzungsfenster == `confirmed`, und der
    Beleg (Query-URN) haengt am Urteil, nicht daneben."""
    g = FakeGms(lineage=[DOWN], query_urns=["urn:li:query:q1"],
                subjects={"urn:li:query:q1": [UP, DOWN]},
                usage_rows={DOWN: [_bucket(NOW - 86_400_000)]})
    m = dt.measure(g, UP, DOWN, NOW)
    assert m["state"] == "confirmed"
    assert m["declared"] is True
    assert m["cooccurrence_queries"] == 1
    assert m["queries_seen"] == 1
    assert m["buckets_checked"] == 1


def test_an_edge_no_source_mentions_is_absent_not_unknown():
    """`unknown` heisst "wir haben hingesehen und konnten nichts sagen".
    Eine Kante, die in KEINER Quelle vorkommt, ist etwas anderes -- sie
    als `unknown` zu melden waere ein erfundener Befund ueber eine Kante,
    die niemand behauptet hat."""
    g = FakeGms(usage_rows={DOWN: [_bucket(NOW - 86_400_000)]})
    assert dt.measure(g, UP, DOWN, NOW)["state"] == "absent"


def test_declared_without_usage_windows_is_unknown_never_dead():
    """Die Kerninvariante des Produkts, hier als Regressionsschutz: keine
    Fenster -> `unknown`. Ein `dead` an dieser Stelle waere die
    Behauptung "nie benutzt" ohne eine einzige Messung."""
    g = FakeGms(lineage=[DOWN])
    m = dt.measure(g, UP, DOWN, NOW)
    assert m["state"] == "unknown"
    assert m["has_window"] is False


def test_measure_until_keeps_every_measurement_including_the_ones_that_missed(monkeypatch):
    """Die Warteschleife darf kein Sieb sein. Wenn der erwartete Zustand
    erst in der dritten Messung steht, muessen alle drei im Artefakt
    landen -- sonst sieht ein Lauf, der 40 s auf den Index gewartet hat,
    aus wie einer, der sofort stimmte."""
    monkeypatch.setattr(dt.time, "sleep", lambda s: None)
    states = iter(["dead", "dead", "confirmed"])
    monkeypatch.setattr(dt, "measure",
                        lambda *a, **kw: {"state": next(states), "evidence": None})

    series, reached = dt.measure_until(object(), UP, DOWN, "confirmed", min_wait_s=0)
    assert [m["state"] for m in series] == ["dead", "dead", "confirmed"]
    assert reached is not None


def test_measure_until_gives_up_and_says_so_instead_of_waiting_forever(monkeypatch):
    """Kein erreichter Zustand ist ein Ergebnis, kein Haenger: die Reihe
    steht da, `reached` ist None, und der Schritt gilt als nicht bewiesen."""
    monkeypatch.setattr(dt.time, "sleep", lambda s: None)
    monkeypatch.setattr(dt, "measure", lambda *a, **kw: {"state": "dead", "evidence": None})

    series, reached = dt.measure_until(object(), UP, DOWN, "confirmed",
                                       min_wait_s=0, max_wait_s=0)
    assert reached is None
    assert len(series) == 1


def test_the_revert_touches_only_the_lines_this_run_appended(tmp_path):
    """`harness/runs/journal.jsonl` traegt Zeilen aelterer Laeufe. Ein
    `revert_all()` auf der ganzen Datei wuerde fremde Arbeit
    zurueckrollen -- deshalb wird nur der eigene Ausschnitt kopiert."""
    fremd = {"entity_type": "dataset", "urn": "urn:li:dataset:(urn:li:dataPlatform:x,fremd,PROD)",
             "aspect": "deprecation", "before": None}
    eigen = {"entity_type": "dataset", "urn": DOWN, "aspect": "upstreamLineage", "before": None}
    g = FakeGms()

    n = dt.revert_journal_slice(g, [json.dumps(eigen)], tmp_path / "slice.jsonl")

    assert n == 1
    assert g.deleted == [("dataset", DOWN, "upstreamLineage")]
    assert all(d[1] != fremd["urn"] for d in g.deleted)


def test_an_empty_slice_reverts_nothing_and_writes_no_file(tmp_path):
    scratch = tmp_path / "slice.jsonl"
    assert dt.revert_journal_slice(FakeGms(), [], scratch) == 0
    assert not scratch.exists()


def test_usage_signature_compares_content_not_just_the_row_count():
    """Drei Zeilen zurueckgespielt ist noch kein Beweis, dass es DIESELBEN
    drei sind -- die Signatur traegt deshalb Summe und Zeitstempel."""
    rows = [_bucket(1000, 5), _bucket(2000, 6)]
    sig = dt.usage_signature(rows)
    assert sig == {"rows": 2, "total_sql_queries": 11,
                   "buckets": [[1000, 5, 2], [2000, 6, 2]]}
    # Vertauschte Werte: gleiche Zeilenzahl, gleiche Summe, gleiche
    # Zeitstempel -- und trotzdem NICHT derselbe Zustand.
    assert dt.usage_signature([_bucket(1000, 6), _bucket(2000, 5)]) != sig


def test_a_shorter_settle_time_is_refused_not_warned_about():
    """Unter 15 s misst man den Index-Verzug, nicht die Wirkung (Falle
    15/21). Ein Hinweis waere hier zu wenig: der Lauf wuerde trotzdem ein
    Artefakt schreiben, das wie ein Beweis aussieht."""
    with pytest.raises(SystemExit):
        dt.main(["--settle-seconds", "2"])


@pytest.mark.parametrize("bad", ["http://localhost:18080", "http://localhost:8080",
                                 "http://example.com:28080"])
def test_forbidden_gms_targets_are_refused(bad):
    """18080 traegt fremde Messdaten, 8080 einen fremden Dienst. Dieses
    Skript SCHREIBT -- ein Tippfehler in der URL waere hier teuer."""
    with pytest.raises(SystemExit):
        dt.main(["--gms-url", bad])
