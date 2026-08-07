"""Die Gestaltungsvorgaben sind bindend (Spec, Abschnitt Gestaltung).
Was pruefbar ist, wird geprueft -- nicht auf Disziplin verlassen."""

import re
from pathlib import Path

CSS = Path("ui/werkbank.css")
HTML = Path("ui/werkbank.html")


def test_every_colour_lives_in_the_token_block_and_nowhere_else():
    """Zwei Quellen, zwei Farben, DURCHGEHEND -- das haelt nur, wenn es
    genau eine Stelle gibt, an der eine Farbe definiert wird."""
    css = CSS.read_text(encoding="utf-8")
    root = re.search(r":root\s*\{.*?\}", css, re.S).group(0)
    outside = css.replace(root, "")
    outside = re.sub(r"@media[^{]*\{[^{}]*\{[^}]*\}[^}]*\}", "", outside, flags=re.S)
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", outside)
    assert not re.findall(r"\b(?:rgb|hsl)a?\(", outside)


def test_the_forbidden_fonts_appear_nowhere():
    css = CSS.read_text(encoding="utf-8")
    for banned in ("Inter", "Space Grotesk"):
        assert banned not in css


def test_no_gradient_anywhere():
    assert "gradient" not in CSS.read_text(encoding="utf-8").lower()


def test_no_emoji_as_section_markers_in_the_markup():
    html = HTML.read_text(encoding="utf-8")
    assert not re.findall(r"[\U0001F300-\U0001FAFF☀-➿]", html)


def test_both_themes_are_defined_and_the_explicit_toggle_wins():
    css = CSS.read_text(encoding="utf-8")
    assert "prefers-color-scheme: dark" in css
    assert 'data-theme="dark"' in css
    assert 'data-theme="light"' in css


def test_keyboard_focus_is_visible_not_removed():
    css = CSS.read_text(encoding="utf-8")
    assert ":focus-visible" in css
    assert "outline: none" not in css.replace(" ", "").replace("outline:none", "outline: none")


def test_numbers_use_tabular_figures_where_they_stack():
    assert "font-variant-numeric: tabular-nums" in CSS.read_text(encoding="utf-8")


def test_the_four_panes_and_the_coverage_banner_exist_by_id():
    html = HTML.read_text(encoding="utf-8")
    for anchor in ("declared-tree", "measured-bars", "edge-ledger", "live-log",
                   "coverage-banner", "mode-badge", "controls"):
        assert f'id="{anchor}"' in html


def test_every_state_carries_its_explaining_sentence_in_the_markup():
    """'Erklaerend eingebaut, nicht als Handbuch daneben' -- wer unknown
    zum ersten Mal sieht, darf nicht raten muessen."""
    html = HTML.read_text(encoding="utf-8")
    for state in ("confirmed", "dead", "missing", "unknown"):
        assert f'data-state-help="{state}"' in html


def test_wide_content_scrolls_in_its_own_container():
    assert "overflow-x: auto" in CSS.read_text(encoding="utf-8")


JS = Path("ui/werkbank.js")


def test_recording_is_the_safe_default_when_the_mode_probe_fails():
    """Eine gescheiterte Abfrage ist keine Abwesenheit -- aber sie darf
    auch nicht als Live-Betrieb durchgehen. Kein Antwort = Aufzeichnung."""
    js = JS.read_text(encoding="utf-8")
    assert "'recording'" in js or '"recording"' in js
    assert "catch" in js


def test_datasets_without_usage_render_as_visibly_empty_not_as_zero():
    """Spec: 'Tabellen ohne Datenlage sind sichtbar leer, nicht auf null
    gesetzt -- der Unterschied muss auch optisch einer sein.'"""
    js = JS.read_text(encoding="utf-8")
    assert "no-data" in js
    assert "bar--empty" in js or "measured--nodata" in js


def test_every_rendered_state_gets_its_explaining_sentence_attached():
    assert "state-help" in JS.read_text(encoding="utf-8")


def test_the_ui_never_sums_buckets_into_a_single_number_for_the_state():
    """Wer die Buckets summiert, macht aus 'nicht gemessen' und 'nichts
    passiert' dieselbe Null -- in der Oberflaeche genauso wie im Code."""
    js = JS.read_text(encoding="utf-8")
    assert "buckets_seen" in js


def test_the_live_badge_uses_the_measured_gms_value_not_a_hardcoded_one():
    """Opus-Review-Nachtrag (MINOR 9): 'Live — buttons write to
    localhost:28080' stand vorher woertlich im Code, obwohl /api/mode den
    echten gms-Wert schon zurueckgibt -- eine unbelegte Behauptung im
    einen Produkt, das genau das nicht tun soll."""
    js = JS.read_text(encoding="utf-8")
    assert "localhost:28080" not in js
    assert "info.gms" in js or "body.gms" in js
