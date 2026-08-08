"""Die Ein-Datei-Ausgabe (`harness/export_static.py`).

Drei Dinge werden hier festgenagelt, weil sie beim naechsten Umbau still
kaputtgehen koennen und niemand es merkt, bis die Datei auf einer fremden
Seite liegt:

  1. **Keine externe Anfrage.** Die Datei wird hinter einer strengen
     Sicherheitsrichtlinie ausgeliefert; ein einziger `src`/`href`/`url()`
     nach draussen und die Seite laedt dort halb.
  2. **Dieselben Zeilen wie der Server.** Eingebacken wird, was
     `ui/console_api.py` liefert -- kein zweiter Bauweg fuer dieselbe Zahl.
  3. **Die schreibenden Knoepfe sind sichtbar ausser Betrieb.** Ein Knopf,
     der nichts tut und dabei aussieht, als taete er etwas, ist genau die
     stille Falschaussage, gegen die dieses Werkzeug antritt.
"""

import json
import re

import pytest
from harness import export_static
from ui import console_api as api
from ui import serve as srv

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    out = tmp_path_factory.mktemp("static") / "werkbank-static.html"
    meta = export_static.export(out)
    return meta, out.read_text(encoding="utf-8")


def test_the_file_stays_under_the_16mb_ceiling(exported):
    meta, _ = exported
    assert not meta["over_limit"], f"{meta['megabytes']} MB"
    assert meta["bytes"] < export_static.SIZE_LIMIT_BYTES


def test_not_one_request_leaves_the_document(exported):
    """Kein `src`, kein `href`, kein `url()`, kein `@import` nach draussen.

    Interne Sprungmarken (`#runs`) sind ausdruecklich in Ordnung -- sie
    loesen keine Anfrage aus.
    """
    _, html = exported
    for attr in ("src", "href"):
        for value in re.findall(rf'{attr}="([^"]*)"', html):
            assert value.startswith("#"), f'{attr}="{value}" verlaesst das Dokument'
    assert "url(" not in html, "eine CSS-url() waere eine externe Anfrage"
    assert "@import" not in html
    # Keine Schrift von aussen: der Stil nennt nur Systemschriften.
    assert "fonts.googleapis" not in html and "@font-face" not in html


def test_style_and_behaviour_are_inlined_not_linked(exported):
    _, html = exported
    assert 'rel="stylesheet"' not in html
    assert "<style>" in html
    assert 'src="werkbank.js"' not in html
    assert '<script type="module">' in html


def test_the_baked_rows_are_the_rows_the_server_would_send(exported):
    """Zeile fuer Zeile dieselbe Menge -- gegen `console_api` gerechnet,
    nicht gegen eine zweite Vorstellung davon."""
    _, html = exported
    payload = json.loads(
        re.search(r"window\.__PROBATE_STATIC__ = (\{.*?\});</script>", html, re.S).group(1)
        .replace("<\\/", "</").replace("<\\!--", "<!--"))

    ledger = srv.load_recorded_ledger()
    judged, _, _ = export_static.load_judgements(ledger)
    expected = api.all_rows(ledger["edges"], judged)

    baked = payload["connections"]["rows"]
    assert len(baked) == len(expected)
    assert [r["edge"] for r in baked] == [r["edge"] for r in expected]
    assert [r["state"] for r in baked] == [r["state"] for r in expected]
    # Die drei Sorten Messung muessen mitkommen -- ohne sie faellt "gemessene
    # Null" wieder mit "nicht gemessen" zusammen (55 Zeilen, gemessen 07.08.).
    assert {r["measurement"] for r in baked} <= {"traffic", "zero", "none"}
    assert [r["measurement"] for r in baked] == [r["measurement"] for r in expected]

    counts = payload["connections"]["state_counts"]
    assert sum(counts.values()) == len(expected)
    assert payload["connections"]["total_unfiltered"] == len(expected)


def test_the_shim_mirrors_every_filter_the_server_has(exported):
    """Die Abfang-Schicht ist eine Doppelung von `filter_sort_page`. Sie
    darf nicht auseinanderlaufen: jeder Filter-Parameter und jeder
    Sortierschluessel der Serverfassung muss darin vorkommen.

    Das faengt den Fall "der Server bekommt einen neuen Filter, die
    Ein-Datei-Ausgabe ignoriert ihn still" -- ein Filter, der wirkungslos
    ist und trotzdem dasteht, ist derselbe Fehlertyp wie ein Knopf ohne
    Wirkung.
    """
    shim = export_static.SHIM_JS
    for param in ("state", "platform", "database", "domain", "owner", "idle",
                  "table", "q", "judged", "abstained", "sort", "dir", "start", "count"):
        assert f"'{param}'" in shim, f"der Filter {param!r} fehlt in der Abfang-Schicht"
    for sort_key in api._SORTS:
        assert re.search(rf"\b{sort_key}: function", shim), f"Sortierung {sort_key!r} fehlt"
    # Der Sonderwert fuer "nachgeschlagen, nichts dran" -- ohne ihn faellt
    # gemessene Abwesenheit mit Unwissen zusammen.
    assert api.NONE_VALUE in shim
    # Derselbe Gruppen-Trenner wie serverseitig: ein Punkt im
    # Datenbanknamen darf nie zwei Gruppen zusammenwerfen.
    assert "\\x1f" in shim


def test_the_writing_buttons_are_visibly_out_of_service(exported):
    _, html = exported
    assert "applyStaticMode" in html
    assert "These buttons are out of service in this copy." in html
    assert "this copy has no catalog behind it" in html.lower()
    # Und die Abfang-Schicht laesst gar keinen Schreibweg zu.
    assert "'/api/action/'" in export_static.SHIM_JS or "/api/action/" in export_static.SHIM_JS
    assert "403" in export_static.SHIM_JS


def test_the_page_says_it_is_a_recording_with_time_and_artifact(exported):
    meta, html = exported
    assert meta["recorded_from"], "ohne Artefaktpfad ist die Aufzeichnung nicht belegt"
    assert meta["recorded_at_iso"]
    assert meta["recorded_from"] in html
    assert "Exported single file" in html


def test_the_catalog_names_its_gap_instead_of_filling_it(exported):
    """Der Katalog dieser Datei ist NICHT der Katalog der Instanz. Das darf
    nicht verschwiegen und nicht mit einer erfundenen Zahl gefuellt
    werden."""
    _, html = exported
    payload = json.loads(
        re.search(r"window\.__PROBATE_STATIC__ = (\{.*?\});</script>", html, re.S).group(1)
        .replace("<\\/", "</").replace("<\\!--", "<!--"))
    note = payload["mode"]["catalog_note"]
    assert "running instance" in note
    assert "Nothing here is estimated." in note
    rows = payload["catalog"]["rows"]
    assert rows, "der aufgezeichnete Lauf hat Tabellen beruehrt, sie gehoeren hinein"
    assert str(len(rows)) in note, "die Zahl im Satz muss die tatsaechliche sein"
    # Jede Zeile traegt ihren Ort -- ein Name ohne Ort ist bei tausenden
    # Datensaetzen wertlos (Spec).
    for row in rows[:20]:
        assert row["platform"] and row["table"]
        assert "checked" in row and "state" in row


def test_a_judgement_about_a_foreign_edge_is_left_out_and_said_so(exported):
    """Die aufgezeichneten Modell-Urteile gehoeren evtl. zu einem ANDEREN
    Lauf. Dann werden sie nicht mitgegeben -- und der Grund steht dabei."""
    meta, html = exported
    payload = json.loads(
        re.search(r"window\.__PROBATE_STATIC__ = (\{.*?\});</script>", html, re.S).group(1)
        .replace("<\\/", "</").replace("<\\!--", "<!--"))
    keys = {e["edge"] for e in payload["current"]["edges"]}
    for j in payload["judgements"]["judgements"]:
        assert j["edge"] in keys, "ein Urteil ueber eine Kante, die es hier nicht gibt"
    if not payload["judgements"]["judgements"]:
        assert meta["judge_note"], "eine leere Urteilsliste braucht ihren Grund"
