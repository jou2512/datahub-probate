"""Zwei gemessene Defekte der Konsole, festgehalten als Test.

Anlass: Joel hat die Werkbank am 07.08.2026 als "funktioniert nicht"
zurueckgewiesen. Im Browser nachgemessen (Chrome, 127.0.0.1:8899):

1. Bei 838x674 lag die Seitenleiste als 838x273-Kasten UEBER dem Inhalt,
   mit EIGENER senkrechter Bildlaufleiste (scrollHeight 399 >
   clientHeight 273) direkt neben der des Inhalts -- "Evidence" war ohne
   Scrollen im Kasten nicht erreichbar.
2. `GET /api/connections` antwortete direkt nach dem Serverstart mit
   `{"rows": [], "total": 0, "has_run": false}`, und die Oberflaeche
   zeigte daraufhin eine WORTLOS leere Tabelle. Von "kaputt" ist das
   nicht zu unterscheiden -- und es verletzt die Null-Regel der Spec
   ("keine Daten" und "gemessene Null" sehen NIE gleich aus), die auf die
   Balken angewendet und auf dem Hauptbildschirm vergessen worden war.

Beide Defekte sind behoben; diese Datei haelt sie fest, damit sie nicht
zurueckkommen.
"""

import json
import re
from pathlib import Path

import pytest

from ui.serve import NOTHING_MEASURED, _provenance, load_recorded_ledger, route

CSS = Path("ui/werkbank.css")
JS = Path("ui/werkbank.js")
HTML = Path("ui/werkbank.html")


def _rules_only(css: str) -> str:
    """Kommentare weg -- diese Datei beschreibt den alten Defekt woertlich
    (`flex-direction: row`), und ein Test, der den Beleg fuer den Defekt
    mit dem Defekt verwechselt, prueft nichts."""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


# --- Defekt 1: das Raster kippt nie in eine Spalte ------------------------


def test_the_sidebar_never_becomes_a_row_above_the_content():
    """Die alte Regel lautete `@media (max-width: 1100px) { .app__body {
    grid-template-columns: minmax(0,1fr) } }` plus `.sidenav {
    flex-direction: row }`. Genau diese beiden Zeilen haben den Kasten
    ueber dem Inhalt erzeugt -- der Beleg steht im Kopf dieser Datei."""
    css = _rules_only(CSS.read_text(encoding="utf-8"))
    body_rules = re.findall(r"\.app__body[^{]*\{[^}]*\}", css)
    assert body_rules, "keine .app__body-Regel gefunden"
    for rule in body_rules:
        cols = re.search(r"grid-template-columns:\s*([^;]+);", rule)
        if not cols:
            continue
        # Eine einzige Spalte hiesse: Seitenleiste und Inhalt untereinander.
        assert "var(--nav-w)" in cols.group(1), rule
    # Und die Seitenleiste selbst bleibt eine SPALTE -- auf jeder Breite.
    for rule in re.findall(r"\.sidenav[^,{]*\{[^}]*\}", css):
        assert "flex-direction: row" not in rule, rule


def test_the_narrow_layout_only_shrinks_the_sidebar():
    """"Darunter nicht zerfallen" heisst: schmaler werden, nicht
    umklappen. Beide schmalen Fassungen setzen deshalb NUR die
    Breiten-Token um."""
    css = _rules_only(CSS.read_text(encoding="utf-8"))
    assert "--nav-w: 210px" in css          # Spec-Breite ab 1280px
    for query in ("max-width: 1279px", "max-width: 1023px"):
        assert f"@media ({query})" in css, query
    narrow = css.split("@media (max-width: 1279px)", 1)[1]
    assert "--nav-w: 150px" in narrow
    assert "--nav-w: 144px" in narrow


def test_the_spec_layout_holds_from_1280_upwards():
    """Ab 1280px darf KEINE Regel mehr eingreifen -- die Spec-Struktur
    (Seitenleiste 210px links, Detailspalte als dritte Spalte) gilt dort
    unveraendert."""
    css = _rules_only(CSS.read_text(encoding="utf-8"))
    widths = [int(m) for m in re.findall(r"@media \(max-width:\s*(\d+)px\)", css)]
    assert widths, "keine Breiten-Umschaltung gefunden"
    assert max(widths) < 1280, f"eine Regel greift noch bei 1280px: {widths}"


def test_only_the_content_row_is_allowed_to_scroll():
    """Ein einziger Bildlauf im Inhaltsbereich (Spec). Die Rasterzeile
    des Inhalts ist die einzige, die waechst."""
    css = _rules_only(CSS.read_text(encoding="utf-8"))
    app = re.search(r"\.app\s*\{[^}]*\}", css).group(0)
    assert "grid-template-rows: auto auto minmax(0, 1fr) auto" in app


# --- Defekt 2: kein Bereich ist jemals wortlos leer ----------------------


def test_the_server_starts_with_the_youngest_recorded_run_not_empty():
    """"Der Server startet nicht mehr leer." Geprueft wird das Artefakt
    selbst, nicht ein Dateiname: es muss Kanten tragen."""
    run = load_recorded_ledger()
    assert run is not None, "kein Lauf-Artefakt gefunden -- die Konsole startet leer"
    assert run["edges"], "das geladene Artefakt traegt keine Kante"
    assert run["recording"] is True
    assert run["live"] is False
    assert run["recorded_from"]
    assert run["recorded_at_iso"]


def test_a_recorded_run_is_never_dressed_up_as_a_live_measurement():
    """Die Wahrheitsfrage dahinter: ein alter Stand, der wie ein neuer
    aussieht, ist genau die Behauptung ohne Beleg, gegen die dieses
    Produkt antritt."""
    run = load_recorded_ledger()
    prov = _provenance(run)
    assert prov["has_run"] is True
    assert prov["replayed"] is True
    assert prov["recorded_at_iso"]
    assert prov["recorded_from"]


def test_a_missing_run_answers_with_a_reason_and_a_fix_not_just_an_empty_list():
    """Der Kern des Defekts: `has_run: false` darf nie ohne Erklaerung
    kommen. Der Grund steht im SERVER, damit ihn keine Ansicht vergessen
    und keine ihn erfinden kann."""
    prov = _provenance(None)
    assert prov["has_run"] is False
    assert prov["empty_reason"] == NOTHING_MEASURED
    assert len(prov["empty_reason"]) > 40
    assert prov["fix_action"] == "run-ledger"


def test_the_stand_still_endpoint_is_routed_and_measures_nothing():
    """`/api/ledger` ist ein echter Lauf gegen GMS (Sekunden, Aufrufe,
    Kosten). Das blosse Oeffnen der Seite darf ihn nicht ausloesen --
    dafuer gibt es `/api/current`."""
    assert route("GET", "/api/current", {}) == ("current", {})
    with pytest.raises((KeyError, ValueError)):
        route("POST", "/api/current", {})
    js = JS.read_text(encoding="utf-8")
    assert "/api/current" in js
    # Gemessen wird nur nach einem Knopfdruck.
    assert "refresh({ measure: true })" in js


@pytest.mark.parametrize("render_fn", [
    "renderOverview", "renderConnections", "renderCatalog",
    "renderRuns", "renderEvidence",
])
def test_every_one_of_the_five_views_explains_its_empty_state(render_fn):
    """Gilt fuer JEDE der fuenf Ansichten, nicht nur fuer Connections."""
    js = JS.read_text(encoding="utf-8")
    body = js.split(f"function {render_fn}(", 1)[1]
    body = body.split("\nfunction ", 1)[0]
    assert re.search(r"blank(Node|Into|Row)\(", body), \
        f"{render_fn} hat keinen erklaerten Leerzustand"


def test_no_view_falls_back_to_a_wordless_empty_table():
    """Die alte Fassung baute leere `<td class="empty-state">`-Zeilen mit
    einem Halbsatz. Ein Leerzustand sagt jetzt IMMER drei Dinge -- was
    fehlt, warum, und der Knopf, der es behebt."""
    js = JS.read_text(encoding="utf-8")
    assert "function blankNode(" in js
    for part in ("blank__what", "blank__why", "empty_reason", "fix_action"):
        assert part in js, part
    css = _rules_only(CSS.read_text(encoding="utf-8"))
    assert ".blank__what" in css and ".blank__why" in css


def test_the_seeded_statement_survives_a_narrow_window():
    """Die Ehrlichkeits-Angabe stand im Fuss der Seitenleiste und war
    damit genau dann weg, wenn das Fenster schmal wurde. Jetzt: eigener
    Streifen ueber voller Breite, in jedem Bereich."""
    html = HTML.read_text(encoding="utf-8")
    assert 'id="notice"' in html
    assert 'id="seeded-note"' in html
    assert 'id="replay-note"' in html
    assert "sidenav__foot" not in html
    js = JS.read_text(encoding="utf-8")
    assert "renderNotice" in js
    assert "Recorded run, not a live measurement." in js


# --- Punkt 3: was am Takt und am Protokoll haerter gemacht wurde ---------


def test_the_log_is_capped_instead_of_growing_forever():
    js = JS.read_text(encoding="utf-8")
    assert "LOG_MAX_LINES" in js
    assert "lastElementChild.remove()" in js


def test_the_ticks_stop_when_nobody_is_looking():
    """Ein verborgener Tab hat nichts von einer Anfrage alle 1,5s -- der
    Server sieht die Last trotzdem."""
    js = JS.read_text(encoding="utf-8")
    assert "visibilityState" in js
    assert "function ticksAllowed(" in js


def test_the_judgement_poll_redraws_only_on_a_real_change():
    js = JS.read_text(encoding="utf-8")
    assert "judgeFingerprint" in js
    assert "function judgeStamp(" in js


def test_the_recorded_artifact_scan_ignores_files_that_are_not_ledgers(tmp_path):
    """`harness/runs/` haelt ueberwiegend Sonden-Protokolle. Nach
    Dateinamen zu raten waere hier der Fehlgriff -- die Pruefung ist
    inhaltlich."""
    (tmp_path / "loadtest.json").write_text(json.dumps({"requests": 5}), encoding="utf-8")
    (tmp_path / "kaputt.json").write_text("{ not json", encoding="utf-8")
    (tmp_path / "leer.json").write_text(json.dumps({"edges": [], "generated_at_ms": 9}),
                                        encoding="utf-8")
    assert load_recorded_ledger([tmp_path], focuses=[]) is None

    (tmp_path / "alt.json").write_text(
        json.dumps({"edges": [{"state": "dead"}], "generated_at_ms": 1000}), encoding="utf-8")
    (tmp_path / "neu.json").write_text(
        json.dumps({"edges": [{"state": "confirmed"}], "generated_at_ms": 2000}),
        encoding="utf-8")
    got = load_recorded_ledger([tmp_path], focuses=[])
    assert got["generated_at_ms"] == 2000
    assert got["recorded_from"].endswith("neu.json")


def test_a_run_about_other_tables_never_wins_over_one_about_ours(tmp_path):
    """Gemessen am 07.08.: "das juengste Artefakt" waere
    `harness/runs/ledger-nach-ereignis.json` gewesen -- eine Kante, deren
    Fokus `probate_seedlab.confirmed_upstream` heisst, eine Tabelle, die
    es unter diesem Namen nicht mehr gibt. Eine Konsole, die als "letzten
    Lauf" einen Lauf ueber FREMDE Tabellen zeigt, ist schlechter als eine
    leere."""
    ours = "urn:li:dataset:(urn:li:dataPlatform:postgres,probate_seedlab.a,PROD)"
    theirs = "urn:li:dataset:(urn:li:dataPlatform:postgres,probate_seedlab.weg,PROD)"
    (tmp_path / "fremd-und-neu.json").write_text(
        json.dumps({"edges": [{"upstream": theirs}], "generated_at_ms": 9000}),
        encoding="utf-8")
    (tmp_path / "unsers-und-alt.json").write_text(
        json.dumps({"edges": [{"upstream": ours}], "generated_at_ms": 1000}),
        encoding="utf-8")
    got = load_recorded_ledger([tmp_path], focuses=[ours])
    assert got["recorded_from"].endswith("unsers-und-alt.json")
    assert got["focus_mismatch"] is False

    # Passt GAR nichts zu den beobachteten Tabellen, wird trotzdem etwas
    # gezeigt -- aber ausdruecklich markiert. Genau dieser Fall liegt am
    # 07.08. vor: alle Artefakte auf der Platte stammen aus der Zeit vor
    # der Umbenennung der Seedlab-Tabellen.
    other = load_recorded_ledger([tmp_path], focuses=["urn:li:dataset:(x,y,PROD)"])
    assert other is not None
    assert other["focus_mismatch"] is True
    assert _provenance(other)["focus_mismatch"] is True
    js = JS.read_text(encoding="utf-8")
    assert "focus_mismatch" in js, "die Oberflaeche sagt den Unterschied nicht"


def test_the_real_artifacts_on_disk_are_ranked_by_scope_not_only_by_age():
    """Gemessen: "das juengste" waere ein Ein-Kanten-Protokoll gewesen
    (`ledger-nach-ereignis.json`, 1 Kante). Gezeigt wird stattdessen der
    Lauf mit den meisten Kanten."""
    run = load_recorded_ledger()
    assert len(run["edges"]) >= 4, run["recorded_from"]
