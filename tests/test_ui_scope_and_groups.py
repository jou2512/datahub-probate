"""Zwei Befunde vom 07.08.2026 abends, als Test festgehalten.

1. **"Run a check" hat den Startzustand zerstoert.** Die Konsole zeigt
   beim Start das aufgezeichnete Register (330 Quelltabellen, 513
   Kanten). Der Knopf lief aber ueber `focus_list` -- die VIER
   Labor-Fokusse aus dem Manifest. Ein Juror drueckt die Hauptaktion und
   sieht statt 513 Zeilen noch 4: der Demo-Katalog ist weg, ohne dass es
   jemand angeordnet haette. Die Spec verbietet genau das ("Kein Knopf,
   dessen Wirkung man erst nach dem Druecken erfaehrt").

   Behoben: der Server misst den SICHTBAREN Umfang und sagt vorher, wie
   gross der ist. Gemessen nach dem Fix (live gegen 28080): 330
   Quelltabellen, 513 Kanten, 1476 API-Aufrufe, 22,8s -- derselbe
   Befund wie die Aufzeichnung (266/73/29/145).

2. **Derselbe Lauf wurde zweimal bezahlt.** `runAction()` schickte die
   Aktion (die intern schon einen vollen Lauf macht) und holte danach
   `/api/ledger` -- noch ein voller Lauf. Bei vier Fokussen unauffaellig,
   beim sichtbaren Umfang sind es zweimal 22,8s und zweimal 1476 Aufrufe
   fuer dasselbe Ergebnis.

Dazu die Gruppierung der Tabelle (Referenz Item-Studio, Spec-Nachtrag):
die Gruppenzeile traegt Summen. Eine Summe, die nicht aufgeht, ist auf
dieser Werkbank teurer als keine -- deshalb wird sie hier nachgerechnet.
"""

import json
import re
from pathlib import Path

import pytest

from ui import console_api as api
from ui.serve import route

LEDGER = Path("harness/runs/demo-katalog-ledger.json")
JS = Path("ui/werkbank.js")
HTML = Path("ui/werkbank.html")


@pytest.fixture(scope="module")
def edges():
    if not LEDGER.exists():  # pragma: no cover -- nur ausserhalb des Repos
        pytest.skip(f"{LEDGER} fehlt")
    return json.loads(LEDGER.read_text(encoding="utf-8"))["edges"]


# --- Befund 1: der Umfang, den man sieht --------------------------------


def test_the_progress_of_a_running_check_is_routed_and_measures_nothing():
    """Ein Lauf ueber den sichtbaren Umfang dauert Sekunden. Ohne einen
    Weg, der den Zaehler liefert, bliebe nur: still warten oder den
    Umfang heimlich verkleinern."""
    assert route("GET", "/api/ledger/progress", {}) == ("ledger-progress", {})
    with pytest.raises((KeyError, ValueError)):
        route("POST", "/api/ledger/progress", {})


def test_the_server_measures_the_scope_that_is_on_screen_not_the_manifest():
    """Die Auswahl steht in `scope_focuses()`: die Fokusse des GEZEIGTEN
    Registers, vereinigt mit den beobachteten. Geprueft wird die
    Herleitung im Quelltext, weil die Funktion eine Schliessung im
    Handler ist -- der Live-Beleg steht im Kopf dieser Datei."""
    src = Path("ui/serve.py").read_text(encoding="utf-8")
    fn = src.split("def scope_focuses(", 1)[1].split("\n    def ", 1)[0]
    assert '_cached_ledger or {}).get("focuses")' in fn
    assert "dict.fromkeys" in fn, "die Reihenfolge muss stabil bleiben"
    # Und der Lauf nimmt wirklich diese Liste, nicht mehr `focus_list`.
    run = src.split("def run_full_ledger(", 1)[1].split("\n    class ", 1)[0]
    assert "wanted = scope_focuses()" in run
    assert "for f in wanted" in run
    assert "for f in focus_list" not in run


def test_the_button_says_what_it_will_measure_before_it_is_pressed():
    html = HTML.read_text(encoding="utf-8")
    assert 'id="run-check-scope"' in html
    js = JS.read_text(encoding="utf-8")
    scope = js.split("function renderRunScope(", 1)[1].split("\nfunction ", 1)[0]
    assert "re-measures" in scope
    assert "source tables" in scope
    # Die Dauer wird GEMESSEN mitgefuehrt, nie geschaetzt.
    assert "run_seconds" in scope


def test_a_check_is_not_paid_for_twice():
    """`run-ledger` IST der Lauf -- danach `/api/ledger` zu holen misst
    dasselbe ein zweites Mal. Die fuenf schreibenden Knoepfe brauchen die
    Nachmessung weiterhin."""
    js = JS.read_text(encoding="utf-8")
    body = js.split("async function runAction(", 1)[1].split("\n// ---", 1)[0]
    assert "refresh({ measure: name !== 'run-ledger' })" in body
    # Und der Balken laeuft mit, statt still zu warten.
    assert "watchRunProgress()" in body
    assert "/api/ledger/progress" in js


def test_the_status_bar_names_the_scope_of_a_check_not_the_focus_flag():
    """Bis heute stand dort "4 observed source tables", waehrend 513
    Kanten auf dem Schirm waren -- die Statusleiste hat den Defekt
    mitgeteilt, ohne dass ihn jemand lesen konnte."""
    js = JS.read_text(encoding="utf-8")
    assert "a check measures ${num(info.scope_focuses)}" in js
    # Der alte Satz nannte die Laenge von `--focus`, nicht den Umfang.
    assert "${(info.focuses || []).length} observed source tables" not in js


# --- Die Gruppenzeile: Summen, die aufgehen ------------------------------


def test_every_group_sum_matches_the_rows_you_then_see(edges):
    """Dieselbe Regel wie bei den Facetten: eine Zahl, die nicht haelt,
    was sie ankuendigt, ist eine Behauptung ohne Beleg."""
    page = api.filter_sort_page(edges, {}, {"count": 1})
    groups = page["groups"]
    assert groups, "keine Gruppen gebildet"
    assert sum(g["total"] for g in groups) == page["total"], \
        "die Gruppen summieren sich nicht auf die Zeilenzahl"
    for g in groups:
        assert g["total"] == g["confirmed"] + g["dead"] + g["missing"] + g["unknown"], g
        got = api.filter_sort_page(
            edges, {}, {"platform": g["platform"], "database": g["database"], "count": 1})
        # Der Plattform/Datenbank-Filter trifft BEIDE Enden einer Kante,
        # die Gruppe nur die Quelle -- die Gruppe kann deshalb kleiner
        # sein, nie groesser.
        assert g["total"] <= got["total"], g


def test_the_group_sort_keeps_a_group_together(edges):
    """Zerfaellt eine Gruppe ueber die Sortierung, erscheint ihre
    Kopfzeile mehrfach und die Summe daneben ist jedes Mal dieselbe --
    eine Ansicht, die sich selbst widerspricht."""
    rows = api.filter_sort_page(edges, {}, {"sort": "group", "count": 200})["rows"]
    seen, order = set(), []
    for r in rows:
        key = api.group_key(r)
        if not order or order[-1] != key:
            assert key not in seen, f"Gruppe {key} kommt ein zweites Mal"
            order.append(key)
            seen.add(key)


def test_the_group_key_cannot_be_confused_by_a_dot_in_a_name():
    """Plattform und Datenbank werden mit einem Steuerzeichen getrennt,
    nicht mit einem Punkt -- sonst koennten zwei verschiedene Paare
    denselben Schluessel bekommen."""
    assert api.GROUP_SEP not in "abcdefghijklmnopqrstuvwxyz._-0123456789"
    a = api.group_key({"from": {"platform": "a.b", "database": "c"}})
    b = api.group_key({"from": {"platform": "a", "database": "b.c"}})
    assert a != b
    # Und der Browser bildet denselben Schluessel, sonst findet er die
    # Summen nicht (gemessen: er fand sie nicht, die Zeile sagte "no
    # group total was measured").
    js = JS.read_text(encoding="utf-8")
    assert re.search(r"groupKey = \(ref\) => `\$\{ref\.platform\}\\x1f\$\{ref\.database\}`", js)


# --- Die Referenz-Struktur, soweit pruefbar ------------------------------


def test_the_sidebar_carries_brand_sections_counts_and_a_system_foot():
    """Ebene 1 der Referenz (Spec-Nachtrag "Die Referenz -- Item-Studio"):
    Markenkachel, Abschnittsueberschriften, Zahl je Punkt, verankerter
    Fuss."""
    html = HTML.read_text(encoding="utf-8")
    assert 'class="sidebar__tile"' in html
    assert html.count('class="sidebar__section"') >= 2
    assert 'class="sidebar__system"' in html
    for count in ("nav-count-connections", "nav-count-catalog",
                  "nav-count-runs", "nav-count-evidence"):
        assert f'id="{count}"' in html, count


def test_the_landing_page_sentence_moved_instead_of_being_deleted():
    """Der Satz ist gut -- er gehoert nur nicht ueber das Arbeitsgeraet.
    Geloescht ist er ausdruecklich nicht: er steht im Bereich, den ein
    Zweifler aufschlaegt."""
    html = HTML.read_text(encoding="utf-8")
    assert "Nobody re-checks those claims." in html
    # Die Bereiche, nicht die Navigationsknoepfe -- beide tragen
    # `data-view`.
    evidence = html.split('class="pane" data-view="evidence"', 1)[1]
    assert "bench__problem" in evidence.split("</header>", 1)[0]
    overview = html.split('class="pane" data-view="overview"', 1)[1]
    assert "bench__problem" not in overview.split('class="pane"', 1)[0]


def test_there_is_exactly_one_filled_primary_action():
    """Spec: "keine zweite Hauptaktion neben Run a check". "Re-check
    everything" war genau das -- derselbe Lauf unter anderem Namen."""
    # Ohne Kommentare: dieser Kopf beschreibt den entfernten Knopf
    # woertlich, und ein Test, der die Beschreibung fuer den Knopf haelt,
    # prueft nichts.
    html = re.sub(r"<!--.*?-->", "", HTML.read_text(encoding="utf-8"), flags=re.S)
    assert html.count("btn--primary") == 1
    assert "Re-check everything" not in html
    assert html.count('data-action="run-ledger"') == 1


def test_the_dark_sidebar_is_dark_in_both_themes():
    """Der groesste Einzeleffekt der Referenz. Eine helle Seitenleiste im
    hellen Thema waere genau der Zustand, der zurueckgewiesen wurde."""
    css = Path("ui/werkbank.css").read_text(encoding="utf-8")
    assert "--nav-bg-light:" in css and "--nav-bg-dark:" in css
    # Die Basisregel am Zeilenanfang -- `.app > .sidebar` setzt nur die
    # Rasterposition.
    rule = re.search(r"^\.sidebar\s*\{[^}]*\}", css, re.M).group(0)
    assert "background: var(--nav-bg)" in rule
