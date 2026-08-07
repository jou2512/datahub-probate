"""Die drei offenen Punkte der Konsole vom 07.08.2026, als Test festgehalten.

1. **Domaene und Besitzer fehlten in der Filterzeile.** Die Spec
   (`docs/werkbank-spec.md`, Bereich 2) verlangt beide Auswahllisten; die
   Daten lagen seit dem Demo-Seed im Katalog, aber niemand las sie.

2. **"Zuletzt belegt" widersprach sich bei toten Kanten.** 32 der 73
   toten Kanten zeigten ein FRISCHES Datum -- technisch richtig (die
   Tabellen hatten Verkehr), in der Zeile aber unlesbar: tot, aber heute
   gemessen? Beim Nachmessen kam ein zweiter, groesserer Fehlgriff heraus:
   55 Zeilen hatten sehr wohl Messfenster, in denen JEDES Fenster null
   gemessen hat -- und die Spalte schrieb "not measured". Eine gemessene
   Null als fehlende Messung auszugeben ist der Verstoss gegen die
   Null-Regel, den dieses Produkt bei anderen anprangert.

3. **`probate_seedlab` stand unbenannt** als sechste Datenbank neben fuenf
   `probate_demo_*` und sah aus wie ein Ausrutscher im Namensschema.

Dazu ein vierter Befund, der beim Bauen auffiel und hier mit festgehalten
wird: die Zahlen in den Auswahllisten zaehlten Kanten-ENDEN statt Kanten.
`probate_seedlab` stand mit "8" da und lieferte nach dem Anklicken 4
Zeilen. Eine Zahl, die nicht haelt was sie ankuendigt, ist auf dieser
Werkbank besonders teuer.
"""

import json
import re
from pathlib import Path

import pytest

from ui import console_api as api

LEDGER = Path("harness/runs/demo-katalog-ledger.json")
GOVERNANCE = Path("harness/runs/demo-katalog-governance.json")
JS = Path("ui/werkbank.js")
HTML = Path("ui/werkbank.html")
CSS = Path("ui/werkbank.css")


@pytest.fixture(scope="module")
def edges():
    if not LEDGER.exists():  # pragma: no cover -- nur ausserhalb des Repos
        pytest.skip(f"{LEDGER} fehlt")
    return json.loads(LEDGER.read_text(encoding="utf-8"))["edges"]


@pytest.fixture(scope="module")
def gov():
    if not GOVERNANCE.exists():  # pragma: no cover
        pytest.skip(f"{GOVERNANCE} fehlt")
    return api.load_governance(GOVERNANCE)


# --- Punkt 1: Domaene und Besitzer ---------------------------------------


def test_domain_and_owner_are_offered_and_come_from_the_data(edges, gov):
    """Nicht hartkodiert (Spec): jeder angebotene Wert muss im gemessenen
    Governance-Artefakt vorkommen."""
    f = api.facets(edges, gov)
    assert f["domains"], "keine Domaenen-Facette"
    assert f["owners"], "keine Besitzer-Facette"

    real_domains = {i["domain"] for i in gov["tables"].values() if i["domain"]}
    real_owners = {o["urn"] for i in gov["tables"].values() for o in i["owners"]}
    for row in f["domains"]:
        assert row["value"] in real_domains or row["value"] == api.NONE_VALUE, row
    for row in f["owners"]:
        assert row["value"] in real_owners or row["value"] == api.NONE_VALUE, row


@pytest.mark.parametrize("facet,param", [("domains", "domain"), ("owners", "owner"),
                                         ("platforms", "platform"), ("databases", "database")])
def test_every_number_in_a_dropdown_is_the_number_of_rows_you_then_see(
        edges, gov, facet, param):
    """DER Test dieser Datei. Bis 07.08. zaehlte die Facette Kanten-ENDEN:
    `probate_seedlab (8)` lieferte 4 Zeilen. Eine Auswahlliste, deren Zahl
    nicht haelt, ist eine Behauptung ohne Beleg."""
    f = api.facets(edges, gov)
    assert f[facet], f"Facette {facet} ist leer"
    for row in f[facet]:
        got = api.filter_sort_page(edges, {}, {param: row["value"], "count": 1}, gov)
        assert got["total"] == row["count"], (
            f"{facet}/{row['value']}: Liste sagt {row['count']}, Tabelle liefert "
            f"{got['total']}")


def test_a_table_nobody_looked_up_is_not_counted_as_having_no_domain(edges):
    """Die Null-Regel auf die Governance angewandt: "nachgeschlagen, keine
    Domaene" und "nie nachgeschlagen" duerfen nie in denselben Topf.
    Ohne Artefakt gibt es deshalb KEINE `__none__`-Facette -- sonst
    stuende dort die Gesamtzahl aller Kanten als vermeintlich gemessene
    Abwesenheit."""
    leer = {"measured": False, "reason": "kein artefakt", "tables": {}}
    f = api.facets(edges, leer)
    assert f["domains"] == []
    assert f["owners"] == []
    assert f["governance"]["measured"] is False
    assert f["governance"]["reason"]


def test_none_selects_measured_absence_only(edges, gov):
    """`__none__` trifft die Enden, die nachgeschlagen wurden und trotzdem
    nichts tragen -- gemessen 4 Seedlab-Tabellen ohne Domaene."""
    got = api.filter_sort_page(edges, {}, {"domain": api.NONE_VALUE, "count": 200}, gov)
    assert got["total"] > 0
    for row in got["rows"]:
        sides = [row["from"], row["to"]]
        assert any(s["known"] and not s["domain"] for s in sides), row["edge"]


def test_two_domains_with_the_same_name_stay_distinguishable(gov):
    """GEMESSEN: `probate_demo.finance` und `probate_seedlab.finance`
    heissen beide "Finance". Zweimal derselbe Eintrag in einer
    Auswahlliste sieht aus wie ein Fehler."""
    labels = api._domain_labels(gov)
    assert len(set(labels.values())) == len(labels), labels
    finance = [v for v in labels.values() if v.startswith("Finance")]
    if len(finance) > 1:
        assert all("(" in v for v in finance), finance


def test_the_filter_row_offers_every_control_the_spec_lists():
    """Spec, Bereich 2, Filtertabelle: Zustand, Plattform, Datenbank,
    Domaene, Besitzer, Zeitraum, zwei Schalter, Freitext."""
    html = HTML.read_text(encoding="utf-8")
    for control in ("filter-states", "filter-platform", "filter-database",
                    "filter-domain", "filter-owner", "filter-idle",
                    "filter-judged", "filter-abstained", "filter-q"):
        assert f'id="{control}"' in html, control


def test_an_active_domain_or_owner_shows_as_a_removable_chip():
    js = JS.read_text(encoding="utf-8")
    chips = js[js.index("function renderActiveFilters"):]
    chips = chips[:chips.index("\nfunction ")]
    for key in ("f.domain", "f.owner", "f.idle"):
        assert key in chips, key
    # Der Chip zeigt die Beschriftung, nicht die URN.
    assert "labelled('domain'" in chips


def test_a_hidden_field_is_really_hidden():
    """`display: flex` auf `.field` schlaegt das Attribut `hidden` --
    gemessen am 07.08.: das Feld fuer den eigenen Zeitraum stand sichtbar
    in der Filterzeile, obwohl die Auswahlliste auf "any" stand."""
    css = re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)
    assert re.search(r"\.field\[hidden\]\s*\{[^}]*display:\s*none", css)


# --- Der Zeitraum-Filter, und warum er anders heisst ----------------------


def test_the_time_filter_never_hides_unmeasured_edges_silently(edges, gov):
    """Kanten ohne jede Messung koennen nicht gealtert werden. Sie
    verschwinden nicht wortlos, sondern werden GEZAEHLT (`unaged`), damit
    die Oberflaeche sie benennen kann."""
    got = api.filter_sort_page(edges, {}, {"idle": "30", "count": 1}, gov)
    assert got["unaged"] > 0
    ohne = sum(1 for e in edges if (e.get("timeline") or {}).get("dead_since_days") is None)
    assert got["unaged"] == ohne
    for row in api.filter_sort_page(edges, {}, {"idle": "30", "count": 200}, gov)["rows"]:
        assert row["dead_since_days"] is not None
        assert row["dead_since_days"] >= 30


def test_without_a_time_filter_nothing_is_reported_as_unaged(edges, gov):
    assert api.filter_sort_page(edges, {}, {"count": 1}, gov)["unaged"] == 0


# --- Punkt 2: die zwei Sorten `dead` und die drei Sorten Messung ----------


def test_a_measured_zero_is_never_reported_as_a_missing_measurement(edges, gov):
    """Die Null-Regel, auf die Spalte "Zuletzt belegt" angewandt. Drei
    Sorten, drei verschiedene Aussagen -- gemessen 399 / 55 / 59."""
    rows = api.filter_sort_page(edges, {}, {"count": 200, "start": 0}, gov)
    seen = set()
    for e in edges:
        r = api.edge_row(e, gov)
        seen.add(r["measurement"])
        cov, tl = e.get("coverage") or {}, e.get("timeline") or {}
        if not (cov.get("buckets_seen") or 0):
            assert r["measurement"] == "none"
        elif tl.get("last_covered_ms"):
            assert r["measurement"] == "traffic"
        else:
            # Fenster gelaufen, alle null: eine GEMESSENE Null.
            assert r["measurement"] == "zero"
    assert seen == {"traffic", "zero", "none"}, seen
    assert rows["total"] == len(edges)


def test_the_two_kinds_of_dead_are_told_apart_in_the_row(edges, gov):
    """"im Fenster nie gemessen" gegen "Query-Quelle befragt, kein Paar".
    Die Herleitung ist STRUKTURELL (gab es Verkehr?), nicht ueber den
    deutschen Freitext in `evidence.reason` -- ein Text, der einer anderen
    Bahn gehoert, ist keine Schnittstelle."""
    kinds = {}
    for e in edges:
        if e.get("state") != "dead":
            continue
        r = api.edge_row(e, gov)
        assert r["dead_kind"] in ("no-pair", "no-window"), r
        kinds[r["dead_kind"]] = kinds.get(r["dead_kind"], 0) + 1
        reason = (e.get("evidence") or {}).get("reason", "")
        # Gegenprobe gegen den Freitext: beide muessen dasselbe sagen.
        if r["dead_kind"] == "no-pair":
            assert "keine paar-abfrage" in reason, reason
        else:
            assert "nie gemessen" in reason, reason
    assert len(kinds) == 2, kinds
    assert sum(kinds.values()) == sum(1 for e in edges if e["state"] == "dead")


def test_only_dead_edges_carry_a_dead_kind(edges, gov):
    for e in edges:
        if e.get("state") != "dead":
            assert api.edge_row(e, gov)["dead_kind"] == ""


def test_the_row_speaks_about_the_edge_not_the_tables_when_they_disagree():
    """Der Widerspruch, den Joel gefunden hat: "tot, aber heute gemessen?".
    Die Zelle sagt jetzt zuerst etwas ueber die KANTE und ordnet das Datum
    danach ausdruecklich den TABELLEN zu."""
    js = JS.read_text(encoding="utf-8")
    cell = js[js.index("function lastMeasuredCell"):]
    cell = cell[:cell.index("\nfunction ")]
    assert "no query joined them" in cell
    assert "both tables active" in cell
    # Und die drei Sorten sind wirklich drei verschiedene Texte.
    assert "not measured" in cell and "measured zero" in cell
    # Rot bleibt den vier in der Spec genannten Stellen vorbehalten.
    assert "chip--dead" not in cell


def test_both_table_paths_use_the_same_cell():
    """Die Aufzeichnung ohne Server rendert dieselbe Zelle -- sonst haenge
    die Wahrheit davon ab, ob gerade ein Server antwortet."""
    js = JS.read_text(encoding="utf-8")
    assert js.count("lastMeasuredCell(") >= 3  # Definition + zwei Aufrufer


# --- Punkt 3: der Namensraum, der kein Ausrutscher ist -------------------


def test_the_lab_namespace_is_named_not_hidden(edges, gov):
    """`probate_seedlab` bleibt SICHTBAR und bekommt dazu, was es ist."""
    notes = api.lab_notes()
    assert notes, "kein Hinweis aus den Artefakten abgeleitet"
    (db, info), = notes.items()
    assert db == "probate_seedlab"
    assert "4-state lab" == info["label"]

    f = api.facets(edges, gov)
    row, = [r for r in f["databases"] if r["value"] == db]
    assert row["note"] == info["label"]
    assert row["count"] > 0, "die Datenbank ist weder versteckt noch leer"
    assert f["database_notes"][db]["note"]


def test_the_lab_note_is_derived_from_artifacts_not_typed(tmp_path):
    """Ein hartkodierter Satz waere morgen falsch, ohne dass es jemand
    merkt. Fehlen die Artefakte, gibt es KEINEN Hinweis statt eines
    erfundenen."""
    assert api.lab_notes(manifest=tmp_path / "gibtsnicht.json") == {}
    # Die Zahlen im Satz stammen aus dem Manifest und dem Uebergangslauf.
    manifest = json.loads(Path("examples/seedlab-manifest.json").read_text(encoding="utf-8"))
    states = {e["expected_edge_state"] for e in manifest["edges"]}
    note = api.lab_notes()["probate_seedlab"]["note"]
    assert f"{len(states)}-state lab" in note
    for s in states:
        assert s in note


def test_no_database_name_is_written_into_the_console_source():
    """Wie `test_no_table_name_is_ever_written_into_the_server_source` in
    test_ui_serve.py: der Namensraum steht im Manifest, nicht im Code."""
    for path in (Path("ui/console_api.py"), JS, HTML):
        text = path.read_text(encoding="utf-8")
        code = re.sub(r"/\*.*?\*/|<!--.*?-->", "", text, flags=re.S)
        code = re.sub(r'"""(?:.|\n)*?"""', "", code)
        # Zeilenkommentare beider Sprachen. `//` nur am Zeilenanfang, damit
        # ein `http://` in einer echten Zeile nicht halb verschluckt wird.
        code = re.sub(r"^\s*(#|//).*$", "", code, flags=re.M)
        assert "probate_seedlab" not in code, path
