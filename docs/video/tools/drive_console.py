"""Faehrt die Werkbank getaktet ab, damit die Bildaufnahme deterministisch wird.

Warum ueberhaupt ein Skript und nicht die Hand: das Drehbuch
(`docs/video-script-final.md`) legt Reihenfolge UND Taktung fest. Von Hand
weicht jede Aufnahme um Sekunden ab, und die eine Einstellung, auf die es
ankommt (0:44, `Disconnect` -> Kante kippt), ist ungeschnitten aufzunehmen --
da darf nichts zappeln.

Wie es klickt: mit dem ECHTEN Mauszeiger (`SetCursorPos` + `mouse_event`), nicht
ueber synthetische DOM-Klicks. Grund: `gdigrab` zeichnet den Zeiger auf, den
Windows zeichnet. Ein CDP-Klick bewegt ihn nicht -- im Video passierten Dinge
dann ohne sichtbare Ursache.

Wo die Koordinaten herkommen: Chrome laeuft im Kiosk-Modus auf einem Monitor,
also faellt der Ursprung des Ansichtsfensters mit dem Ursprung des Monitors
zusammen. `getBoundingClientRect()` (CSS-Pixel) * devicePixelRatio + Monitor-
Ursprung = Bildschirmpunkt. Kein Raten ueber Fensterrahmen.

Aufruf:
    uv run --python 3.11 --with websocket-client python docs/video/tools/drive_console.py --probe
    uv run --python 3.11 --with websocket-client python docs/video/tools/drive_console.py --dry-run
    uv run --python 3.11 --with websocket-client python docs/video/tools/drive_console.py --take

`--dry-run` fasst NICHTS an, was schreibt (kein `Disconnect`) -- es misst nur
Wege und Zeiten. `--measure-flip` macht den Schnitt wirklich und misst, wie
lange die Konsole braucht, bis die Kante kippt. `--take` ist der volle Ablauf.

NIEMALS gegen 18080 oder 8080. Die Konsole spricht mit 28080, das ist ihre
Sache; dieses Skript spricht nur mit der Konsole.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parents[3]
CONSOLE_URL = "http://127.0.0.1:8899/werkbank.html"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
DEBUG_PORT = 9333

# Der Monitor, auf dem gedreht wird. 1920x1080 ist das Zielformat; der
# zweite Schirm hat es nativ, der erste (3440x1440) nicht. Ueberschreibbar.
MON_X, MON_Y, MON_W, MON_H = -1920, 209, 1920, 1080

MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004


# --------------------------------------------------------------- Maus (echt)

def _dpi_aware() -> None:
    """Ohne das rechnet Windows unsere Koordinaten heimlich um."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE_V2
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def cursor_to(x: int, y: int) -> None:
    ctypes.windll.user32.SetCursorPos(int(x), int(y))


def cursor_pos() -> tuple[int, int]:
    pt = ctypes.wintypes.POINT() if hasattr(ctypes, "wintypes") else None
    if pt is None:
        import ctypes.wintypes as wt
        pt = wt.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def glide(x: int, y: int, seconds: float = 0.6, steps: int | None = None) -> None:
    """Zeiger sichtbar bewegen. Ein Sprung sieht im Video aus wie ein Fehler."""
    sx, sy = cursor_pos()
    steps = steps or max(2, int(seconds * 60))
    for i in range(1, steps + 1):
        t = i / steps
        e = t * t * (3 - 2 * t)  # smoothstep: startet und endet ruhig
        cursor_to(sx + (x - sx) * e, sy + (y - sy) * e)
        time.sleep(seconds / steps)


def click_here() -> None:
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.06)
    ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


# ---------------------------------------------------------------------- CDP

class CDP:
    def __init__(self, port: int = DEBUG_PORT):
        import websocket  # via `uv run --with websocket-client`

        last = None
        for _ in range(60):
            try:
                raw = urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/json", timeout=2).read()
                pages = [t for t in json.loads(raw)
                         if t.get("type") == "page" and "werkbank" in (t.get("url") or "")]
                if not pages:
                    pages = [t for t in json.loads(raw) if t.get("type") == "page"]
                if pages:
                    # `suppress_origin` ist nicht optional: websocket-client
                    # schickt sonst einen Origin-Kopf, und Chrome lehnt einen
                    # DevTools-Socket mit Origin ab (403, ohne Text). Gemessen
                    # 10.08.2026 -- ohne das Flag scheitert JEDE Verbindung,
                    # und der Fehler sieht aus wie "Port nicht offen".
                    self.ws = websocket.create_connection(
                        pages[0]["webSocketDebuggerUrl"], timeout=90,
                        suppress_origin=True)
                    self._id = 0
                    return
            except Exception as err:      # noqa: BLE001 -- der Grund wird gezeigt
                last = err
            time.sleep(0.5)
        raise RuntimeError(f"kein DevTools-Socket auf {port}: {last!r}")

    def send(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": method,
                                 "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self._id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def js(self, expr: str):
        r = self.send("Runtime.evaluate", {
            "expression": expr, "returnByValue": True, "awaitPromise": True})
        res = r.get("result", {})
        if r.get("exceptionDetails"):
            raise RuntimeError(f"JS: {r['exceptionDetails'].get('text')} :: {expr[:120]}")
        return res.get("value")

    def navigate(self, url: str) -> None:
        self.send("Page.navigate", {"url": url})


# ------------------------------------------------------------------- Ablauf

class Director:
    """Haelt die Uhr, die Marken und die Umrechnung Element -> Bildschirm."""

    def __init__(self, cdp: CDP, mon=(MON_X, MON_Y), verbose=True):
        self.cdp = cdp
        self.mx, self.my = mon
        self.t0 = time.perf_counter()
        self.marks: list[dict] = []
        self.verbose = verbose
        self.dpr = float(cdp.js("window.devicePixelRatio") or 1)

    # -- Zeit ------------------------------------------------------------
    @property
    def t(self) -> float:
        return time.perf_counter() - self.t0

    def mark(self, name: str, kind: str = "segment") -> None:
        self.marks.append({"name": name, "kind": kind, "t": round(self.t, 3)})
        if self.verbose:
            print(f"[{self.t:7.2f}] MARK {kind:8s} {name}", flush=True)

    def note(self, text: str) -> None:
        if self.verbose:
            print(f"[{self.t:7.2f}]      {text}", flush=True)

    def hold_until(self, t_abs: float) -> None:
        """Wartet, bis die Uhr t_abs erreicht. Nie rueckwaerts."""
        d = t_abs - self.t
        if d > 0:
            time.sleep(d)
        elif d < -0.35:
            self.note(f"!! {-d:.2f}s ueber Plan -- der Schnitt wird laenger")

    # -- Geometrie -------------------------------------------------------
    def rect(self, finder_js: str) -> dict:
        r = self.cdp.js(
            "(() => { const e = " + finder_js + ";"
            " if (!e) return null; const r = e.getBoundingClientRect();"
            " return {x:r.x, y:r.y, w:r.width, h:r.height}; })()")
        if not r:
            raise RuntimeError(f"Element nicht gefunden: {finder_js[:120]}")
        return r

    def screen_point(self, r: dict, fx: float = 0.5, fy: float = 0.5) -> tuple[int, int]:
        return (int(self.mx + (r["x"] + r["w"] * fx) * self.dpr),
                int(self.my + (r["y"] + r["h"] * fy) * self.dpr))

    def point_at(self, finder_js: str, fx=0.5, fy=0.5, seconds=0.6) -> tuple[int, int]:
        x, y = self.screen_point(self.rect(finder_js), fx, fy)
        glide(x, y, seconds)
        return x, y

    def click(self, finder_js: str, fx=0.5, fy=0.5, seconds=0.6, settle=0.35) -> None:
        self.point_at(finder_js, fx, fy, seconds)
        click_here()
        time.sleep(settle)

    def sweep(self, finder_js: str, seconds=3.0) -> None:
        """Zeiger langsam ueber ein Element ziehen -- fuer die Zahl in 0:00."""
        r = self.rect(finder_js)
        x0, y = self.screen_point(r, 0.08, 0.55)
        x1, _ = self.screen_point(r, 0.92, 0.55)
        glide(x0, y, seconds * 0.3)
        glide(x1, y, seconds * 0.7)

    def wait_js(self, expr: str, timeout=90.0, poll=0.25) -> float:
        start = time.perf_counter()
        while time.perf_counter() - start < timeout:
            if self.cdp.js(expr):
                return time.perf_counter() - start
            time.sleep(poll)
        raise TimeoutError(f"Bedingung blieb falsch: {expr[:120]}")


# ---------------------------------------------------------- JS-Fundstellen

NAV = '.sidenav__item[data-view="{}"]'
J_NAV = "document.querySelector('{}')"


def j_nav(view: str) -> str:
    return f"document.querySelector('.sidenav__item[data-view=\"{view}\"]')"


def j_kpi(state: str) -> str:
    # Die vier Kennzahlkarten. Ueber den Zustandsnamen gesucht, nicht ueber
    # die Position -- eine Reihenfolge im DOM ist keine Zusicherung.
    return ("[...document.querySelectorAll('#run-verdict *')].find("
            f"e => e.children.length===0 && /{state}/i.test(e.textContent))"
            "?.closest('.kpi, .card, div')")


def j_row(fragment: str) -> str:
    return ("[...document.querySelectorAll('#edge-rows tr.is-selectable')].find("
            f"tr => tr.textContent.includes({fragment!r}))")


def j_chip(state: str) -> str:
    return f"document.querySelector('#filter-states .chip--{state}')"


def j_action(name: str) -> str:
    return f"document.querySelector('button[data-action=\"{name}\"]')"


def row_state(fragment: str) -> str:
    return ("(() => { const tr = " + j_row(fragment) + ";"
            " return tr ? tr.querySelector('.chip')?.textContent.trim() : null; })()")


# ------------------------------------------------------------------ Aufbau

def _seed_profile(profile: Path) -> None:
    """Die Uebersetzungs-Blase abschalten, bevor Chrome startet.

    Gemessen 10.08.2026: `--disable-features=Translate,TranslateUI` genuegt in
    Chrome 150 NICHT -- die Blase stand im Testbild oben rechts. Was greift,
    ist die Einstellung im Profil selbst. Ein Fremdkoerper im Bild ist kein
    Schoenheitsfehler: er lenkt genau an der Stelle ab, an der ein Juror
    entscheidet weiterzuschauen.
    """
    d = profile / "Default"
    d.mkdir(parents=True, exist_ok=True)
    prefs = d / "Preferences"
    data = {}
    if prefs.exists():
        try:
            data = json.loads(prefs.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data.setdefault("translate", {})["enabled"] = False
    data.setdefault("translate_blocked_languages", ["en"])
    data.setdefault("intl", {})["accept_languages"] = "en-US,en"
    data.setdefault("browser", {})["has_seen_welcome_page"] = True
    prefs.write_text(json.dumps(data), encoding="utf-8")


def start_chrome(profile: Path, url: str) -> subprocess.Popen:
    _seed_profile(profile)
    args = [CHROME,
            f"--user-data-dir={profile}",
            f"--remote-debugging-port={DEBUG_PORT}",
            f"--window-position={MON_X},{MON_Y}",
            f"--window-size={MON_W},{MON_H}",
            "--kiosk",
            "--no-first-run", "--no-default-browser-check",
            "--disable-session-crashed-bubble", "--hide-crash-restore-bubble",
            "--disable-infobars", "--lang=en-US",
            "--autoplay-policy=no-user-gesture-required",
            # Ohne diese drei nimmt `gdigrab -i title=…` ein SCHWARZES Bild
            # auf (gemessen 10.08.2026: 3 s Aufnahme, nur der Mauszeiger war
            # zu sehen). Chrome zeichnet dann auf der GPU, und GDI sieht
            # nichts. Desktop-Aufnahme waere die bequeme Ausweichloesung --
            # sie ist ausgeschlossen, weil auf diesem Rechner Recherche ueber
            # andere Teams, Slack und Mail offen liegen.
            # `--disable-direct-composition` ist der Schluessel. Gemessen
            # 10.08.2026, drei Aufnahmen: ohne ihn ist das Bild SCHWARZ, auch
            # mit `--disable-gpu` allein -- Chrome zeichnet ueber
            # DirectComposition, und GDI sieht davon nichts. Mit ihm steht
            # die ganze Konsole im Bild.
            "--disable-gpu", "--disable-direct-composition",
            "--disable-features=CalculateNativeWinOcclusion,Translate,"
            "TranslateUI,TranslateSubframes",
            url]
    return subprocess.Popen(args)


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0


def preflight(cdp: CDP) -> dict:
    """Die Vorbedingungen aus dem Drehbuch, geprueft statt geglaubt."""
    out = {}
    out["mode"] = cdp.js("document.getElementById('mode-badge')?.textContent.trim()")
    out["has_rows"] = cdp.js("!!document.querySelector('#edge-rows tr')")
    out["kpi_text"] = cdp.js("document.getElementById('run-verdict')?.innerText")
    out["seeded_visible"] = cdp.js(
        "(() => { const n = document.getElementById('seeded-note');"
        " return !!n && !n.hidden && !!n.textContent.trim(); })()")
    out["viewport"] = cdp.js("[innerWidth, innerHeight, devicePixelRatio]")
    return out


# --------------------------------------------------------------- Die Namen
#
# Kein Tabellenname steht hier als Literal. `examples/seedlab-manifest.json`
# ist die einzige Wahrheit darueber, wie die geseedeten Tabellen heissen
# (dieselbe Begruendung wie in `ui/serve.py`: ein Name im Quelltext ist eine
# Zeitbombe, sobald das Labor umbenannt wird). Die Zuordnung Rolle -> Tabelle
# kommt zusaetzlich live von `/api/mode` bzw. `/api/connections`.

def lab_names() -> dict:
    import urllib.request
    req = urllib.request.Request(
        "http://127.0.0.1:8899/api/connections?q=probate_seedlab&count=50",
        headers={"X-Probate": "1"})
    rows = json.loads(urllib.request.urlopen(req, timeout=20).read())["rows"]
    by_state = {}
    for r in rows:
        by_state.setdefault(r["state"], []).append(r)
    missing = [s for s in ("confirmed", "dead") if s not in by_state]
    if missing:
        raise RuntimeError(
            f"Das Demo-Labor zeigt keine {missing}-Kante. "
            "harness/seed_lineage_lab.py laufen lassen, dann seedlab_verdicts.py.")
    return {
        "dead_row": by_state["dead"][0]["to"]["table"],
        "confirmed_row": by_state["confirmed"][0]["to"]["table"],
        "confirmed_from": by_state["confirmed"][0]["from"]["table"],
    }


# ---------------------------------------------------------------- Die Bilder
#
# Ein Abschnitt = eine Funktion. Jede bekommt ihr Zeitbudget aus
# `docs/video/timing.json` und muss es einhalten: `d.hold_until(ende)`.

def scroll_to_text(d: Director, needle: str, margin: int = 120) -> bool:
    """Zu einer Textstelle scrollen -- ueber einen Range, nicht ueber Mathematik.

    Der naheliegende Weg (Zeilennummer x Zeilenhoehe) ist falsch, sobald der
    Text umbricht: `white-space: pre-wrap` macht aus einer Textzeile mehrere
    Bildzeilen, und die Rechnung landet weit oberhalb. Gemessen 10.08.2026 --
    der README-Schnitt stand auf "The four states" statt auf der Tabelle der
    widerlegten Behauptungen. Ein `Range` misst, wo der Text WIRKLICH steht.
    """
    return bool(d.cdp.js(
        "(() => { const p = document.querySelector('pre'); if (!p) return false;"
        " const tn = p.firstChild; if (!tn || tn.nodeType !== 3) return false;"
        f" const i = tn.textContent.toLowerCase().indexOf({needle.lower()!r});"
        " if (i < 0) return false;"
        " const r = document.createRange();"
        f" r.setStart(tn, i); r.setEnd(tn, i + {len(needle)});"
        " const box = r.getBoundingClientRect();"
        f" window.scrollBy(0, box.top - {margin});"
        " return true; })()"))


# --------------------------------------------------- Mitschriften im Browser
#
# Die vier Kommandozeilen-Abschnitte laufen NICHT in einem Terminalfenster.
# Gemessen 10.08.2026: `gdigrab -i title=…` nimmt von einem Windows-11-
# Konsolenfenster ein schwarzes Bild auf (DirectX-Renderer, GDI sieht nichts),
# und Desktop-Aufnahme ist ausgeschlossen, weil auf diesem Rechner Recherche
# ueber andere Teams, Slack und Mail offen liegen. Also laufen die Befehle
# wirklich (`transcripts.py`) und ihre Ausgabe wird als Textdatei im selben
# Browserfenster gezeigt -- so wie die Lauf-Artefakte in 1:17 und 2:23 auch.

TRANSCRIPT_CSS = (
    "(() => { const p = document.querySelector('pre'); if (!p) return false;"
    " document.documentElement.style.background='#0d1117';"
    " document.body.style.background='#0d1117'; document.body.style.margin='0';"
    " p.style.color='#d7dde5'; p.style.background='#0d1117';"
    " p.style.fontFamily='Consolas, monospace'; p.style.fontSize='27px';"
    " p.style.lineHeight='1.45'; p.style.padding='40px 48px';"
    " p.style.whiteSpace='pre-wrap'; p.style.margin='0'; return true; })()")


def seg_transcript(d: Director, seg_id: str, dur: float) -> None:
    """Eine Mitschrift zeigen. Marke faellt erst, wenn sie im Bild steht."""
    f = ROOT / "docs/video/transcripts" / f"{seg_id}.txt"
    if not f.exists():
        raise RuntimeError(
            f"Mitschrift fehlt: {f}. Erst transcripts.py laufen lassen.")
    d.cdp.navigate(f.as_uri())
    d.wait_js("!!document.querySelector('pre') && "
              "document.querySelector('pre').innerText.trim().length > 40",
              timeout=20)
    d.cdp.js(TRANSCRIPT_CSS)
    d.cdp.js("window.scrollTo(0,0); true;")
    d.mark(seg_id)
    d.hold_until(d.t + dur)


def seg_01_payoff(d: Director, names: dict, dur: float) -> None:
    d.mark("01-payoff")
    end = d.t + dur
    # `showView` ist nicht global (Modul-Bereich) -- ueber den
    # Navigationsknopf gehen, denselben Weg, den ein Mensch nimmt.
    d.cdp.js("document.querySelector('.sidenav__item[data-view=\"overview\"]')"
             ".click(); window.scrollTo(0,0); true;")
    # Zeiger parkt unten rechts, ausserhalb der Kennzahlen -- er soll die
    # Zahl nicht schon verdecken, bevor sie gesprochen ist.
    glide(d.mx + int(MON_W * 0.72), d.my + int(MON_H * 0.82), 0.5)
    d.hold_until(min(end - 1.0, d.t + 4.0))
    try:
        d.sweep(j_kpi("dead"), seconds=3.2)
    except RuntimeError:
        d.note("Kennzahlkarte 'Dead' nicht gefunden -- Zeiger bleibt stehen")
    d.hold_until(end)


def seg_02_seeded(d: Director, names: dict, dur: float) -> None:
    d.mark("02-seeded")
    end = d.t + dur
    d.cdp.js("window.scrollTo({top:0, behavior:'smooth'});")
    time.sleep(0.6)
    try:
        d.point_at("document.getElementById('seeded-note')", 0.12, 0.5, 1.0)
        d.point_at("document.getElementById('seeded-note')", 0.88, 0.5, 2.4)
    except RuntimeError:
        d.note("seeded-note nicht sichtbar -- VORBEDINGUNG VERLETZT")
    d.hold_until(end)


def seg_03_dead_edge(d: Director, names: dict, dur: float) -> None:
    d.mark("03-dead-edge")
    end = d.t + dur
    d.click(j_nav("connections"), seconds=0.8, settle=0.9)
    d.click(j_chip("dead"), seconds=0.7, settle=1.2)
    d.click(j_row(names["dead_row"]), 0.35, 0.5, seconds=0.8, settle=1.2)
    # Auf den Beleg zeigen: erst den Urteilssatz (er nennt das Datum im
    # Klartext), dann die Balkenreihe. Klassennamen abgelesen aus
    # `ui/werkbank.js` (`detail__sentence`, `spark`, `spark--empty`) -- nicht
    # geraten, sonst zeigt der Zeiger ins Leere und niemand merkt es.
    for finder in (
        "document.querySelector('#detail-body .detail__sentence')",
        "document.querySelector('#detail-body .spark, #detail-body .spark--empty,"
        " #detail-body .spark__axis')",
    ):
        try:
            d.point_at(finder, 0.5, 0.5, 1.4)
            time.sleep(1.2)
        except RuntimeError:
            d.note(f"Beleg-Element nicht gefunden ({finder[:40]}…)")
    d.hold_until(end)


def seg_04a_flip_before(d: Director, names: dict, dur: float) -> None:
    """Bis unmittelbar VOR den Klick. Der Klick gehoert in den naechsten Schnitt."""
    d.mark("04a-flip-before")
    end = d.t + dur
    # Zustands-Chip wieder abwaehlen, damit die bestaetigte Kante sichtbar ist.
    d.click(j_chip("dead"), seconds=0.7, settle=1.2)
    d.click(j_row(names["confirmed_row"]), 0.35, 0.5, seconds=0.8, settle=1.4)
    d.click(j_nav("overview"), seconds=0.8, settle=0.8)
    d.cdp.js("document.querySelector('button[data-action=\"cut-warehouse\"]')"
             "?.scrollIntoView({block:'center'});")
    time.sleep(0.6)
    # Erst auf den SATZ zeigen, der sagt, was der Knopf tut, dann druecken.
    # Ein Knopf, dessen Wirkung man erst nach dem Druecken erfaehrt, ist
    # genau das, was diese Konsole nicht sein will (werkbank-spec.md).
    d.point_at("document.querySelector('button[data-action=\"cut-warehouse\"]')"
               ".closest('.actionrow').querySelector('.actionrow__writes')",
               0.5, 0.5, 1.2)
    d.hold_until(max(0.0, end - 0.9))
    d.point_at(j_action("cut-warehouse"), 0.5, 0.5, 0.8)
    d.hold_until(end)


def seg_04b_cut(d: Director, names: dict, dur: float, *, write: bool) -> None:
    """Der Klick, die Protokollzeile, der Halt.

    Hier steht der 3-Sekunden-Beat aus dem Drehbuch, ungeschnitten und
    unbeschleunigt. Er wartet aber NICHT mehr auf die Neumessung der
    Konsole: die misst nach jedem Knopfdruck ihren ganzen sichtbaren Umfang
    neu (330 Fokusse), gemessen am 10.08.2026 in vier Laeufen mit
    27.96 / 28.68 / 31.75 / 33.75 s. Der Fortschrittsbalken laeuft in
    diesem Bild sichtbar an -- was er zu Ende bringt, sieht man nicht mehr,
    weil der naechste Schnitt dieselbe Kante an der Kommandozeile neu misst
    (1.25 s gemessen) und den Zustand als Text zeigt. Das ist mehr Beleg,
    nicht weniger.
    """
    d.mark("04b-cut")
    end = d.t + dur
    if write:
        click_here()          # der Zeiger steht bereits auf dem Knopf
        d.mark("disconnect-click", kind="event")
    else:
        d.note("TROCKENLAUF: Disconnect wird NICHT gedrueckt")
        d.mark("disconnect-click-skipped", kind="event")
    # Auf die Protokollzeile warten -- sie ist der sichtbare Beleg, dass
    # geschrieben wurde. Sie kommt in Bruchteilen einer Sekunde.
    if write:
        try:
            waited = d.wait_js(
                "/purged|coverage collapses/i.test("
                "document.getElementById('live-log')?.innerText || '')", timeout=20)
            d.note(f"Protokollzeile nach {waited:.2f} s")
            d.mark("live-log-line", kind="event")
        except TimeoutError:
            d.note("!! keine Protokollzeile — der Knopf hat nicht geschrieben")
    d.cdp.js("document.getElementById('live-log')?.scrollIntoView({block:'center'});")
    # Waehrend der Halt laeuft, misst die Kommandozeile dieselbe Kante neu
    # (1.25 s). Das passiert im Hintergrund, damit der naechste Schnitt nicht
    # mit einem leeren Bild beginnt -- und es passiert JETZT, weil die
    # Nutzungsdaten genau jetzt weg sind.
    if write:
        import threading
        d._transcript = threading.Thread(
            target=lambda: subprocess.run(
                [sys.executable, str(Path(__file__).with_name("transcripts.py")),
                 "--which", "04c"], cwd=ROOT, capture_output=True),
            daemon=True)
        d._transcript.start()
    try:
        d.point_at("document.getElementById('live-log')", 0.25, 0.2, 1.0)
    except RuntimeError:
        pass
    d.hold_until(end)


def seg_05_transitions(d: Director, names: dict, dur: float) -> None:
    """Nur das Artefakt. Die Lauf-Liste der Konsole ist dieselbe Aussage in
    schwaecherer Form und kostet Sekunden, die der Schnitt nicht hat.

    Die Marke faellt NACH dem Laden. Vorher gesetzt, begann der Schnitt mit
    1.5 s alter Konsole im Bild -- gemessen am Probelauf 10.08.2026. Was das
    Laden kostet, zahlt der vorige Abschnitt, nicht dieser.
    """
    art = (ROOT / "harness/runs/demo-transitions.json").as_uri()
    d.cdp.navigate(art)
    d.wait_js("!!document.querySelector('pre') && "
              "document.querySelector('pre').innerText.includes("
              "'transitions_proven')", timeout=20)
    d.cdp.js("(() => { const p = document.querySelector('pre');"
             " if (p) { p.style.fontSize='26px'; p.style.lineHeight='1.5';"
             " p.style.padding='24px'; } return true; })()")
    if not scroll_to_text(d, "transitions_attempted", margin=260):
        d.note("Artefakt: 'transitions_attempted' nicht gefunden")
    d.mark("05-transitions")
    d.hold_until(d.t + dur)


def seg_08_close(d: Director, names: dict, dur: float) -> None:
    """README: erst die drei widerlegten Behauptungen, dann die Grenzen.

    Marke wieder nach dem Laden -- siehe seg_05_transitions.
    """
    d.cdp.navigate((ROOT / "README.md").as_uri())
    d.wait_js("!!document.querySelector('pre') && "
              "document.querySelector('pre').innerText.length > 1000", timeout=25)
    d.cdp.js("(() => { const p = document.querySelector('pre');"
             " if (p) { p.style.fontSize='21px'; p.style.lineHeight='1.55';"
             " p.style.padding='24px'; p.style.whiteSpace='pre-wrap'; }"
             " return true; })()")
    if not scroll_to_text(d, "Three things we believed", margin=140):
        d.note("README: Tabelle der widerlegten Behauptungen nicht gefunden")
    d.mark("08-close")
    end = d.t + dur
    d.hold_until(d.t + dur * 0.40)
    if not scroll_to_text(d, "## Honest limitations", margin=120):
        d.note("README: 'Honest limitations' nicht gefunden")
    d.hold_until(end)


# -------------------------------------------------------------------- main

# Alles in EINEM Durchgang und in EINEM Fenster -- der ganze Schnitt ausser
# der Endkarte. Frueher waren es drei Aufnahmen (Konsole + zwei Terminals);
# das Terminalfenster war nicht aufnehmbar (siehe seg_transcript).
CONSOLE_SEGMENTS = ["01-payoff", "02-seeded", "03-dead-edge", "04a-flip-before",
                    "04b-cut", "04c-reveal", "05-transitions", "06-model",
                    "07-gate", "07b-mcp", "08-close"]


def load_timing() -> dict:
    p = ROOT / "docs/video/timing.json"
    if not p.exists():
        raise SystemExit("docs/video/timing.json fehlt — erst plan_timing.py laufen lassen.")
    t = json.loads(p.read_text(encoding="utf-8"))
    return {s["id"]: s for s in t["segments"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="nur nachsehen, nichts fahren")
    ap.add_argument("--dry-run", action="store_true",
                    help="ganzer Ablauf, aber `Disconnect` wird nicht gedrueckt")
    ap.add_argument("--take", action="store_true", help="der echte Durchlauf")
    ap.add_argument("--keep-chrome", action="store_true")
    ap.add_argument("--no-prerun", action="store_true",
                    help="den 30-Sekunden-Vorlauf ueberspringen (nur zum Ueben)")
    ap.add_argument("--lead-in", type=float, default=2.0,
                    help="Vorlauf in Sekunden, bevor der erste Abschnitt beginnt")
    ap.add_argument("--marks", default="docs/video/marks.json")
    ap.add_argument("--record", default=None,
                    help="Rohaufnahme hierhin (fenstergenau, .mkv)")
    args = ap.parse_args()
    if not (args.probe or args.dry_run or args.take):
        ap.error("eines von --probe / --dry-run / --take")

    _dpi_aware()
    if not shutil.which("ffprobe"):
        print("Hinweis: ffprobe nicht im PATH — Messen geht dann nicht.")

    profile = Path(tempfile.gettempdir()) / "probate-video-chrome"
    proc = None
    if not port_open(DEBUG_PORT):
        profile.mkdir(parents=True, exist_ok=True)
        proc = start_chrome(profile, CONSOLE_URL)
        time.sleep(1.0)
        time.sleep(2.5)
    cdp = CDP()
    cdp.send("Page.enable")
    cdp.send("Runtime.enable")
    # Falls Chrome schon lief und woanders stand.
    if "werkbank" not in (cdp.js("location.href") or ""):
        cdp.navigate(CONSOLE_URL)
        time.sleep(2.0)

    pre = preflight(cdp)
    print(json.dumps(pre, indent=2, ensure_ascii=False))
    if args.probe:
        if not args.keep_chrome and proc:
            proc.terminate()
        return 0

    if not (pre["mode"] or "").lower().startswith("live"):
        print(f"!! mode-Abzeichen liest '{pre['mode']}', nicht 'live'. "
              "Die Konsole erreicht GMS nicht — jede Einstellung waere gelogen.")
        return 2

    # Vorbedingung 5: einmal messen lassen, damit die Karten echte Zahlen
    # tragen. Das dauert ~30 s (330 Fokusse) und passiert VOR der Aufnahme.
    # Ohne diesen Schritt zeigt die Uebersicht den Stand des letzten Laufs
    # dieses Prozesses -- nach einem Test also 265/146 statt 266/145.
    if not args.no_prerun:
        print("Vorlauf: 'Run check' … (das dauert ~30 s, noch ohne Kamera)")
        t0 = time.perf_counter()
        cdp.js("document.getElementById('run-check').click(); true;")
        time.sleep(1.0)
        for _ in range(400):
            if cdp.js("(() => { const p = document.getElementById('run-progress');"
                      " return !!p && p.hidden; })()"):
                break
            time.sleep(0.5)
        print(f"Vorlauf fertig nach {time.perf_counter() - t0:.1f} s")

    kpi = (cdp.js("document.getElementById('run-verdict')?.innerText") or "")
    want = {"266": "confirmed", "73": "dead", "29": "missing", "145": "not judged"}
    missing = [n for n in want if n not in kpi]
    if missing:
        print("!! Die Uebersicht zeigt nicht die Zahlen aus dem Drehbuch "
              f"(fehlen: {missing}). Gesehen:\n{kpi}\n"
              "Das Demo-Labor ist nicht im Ausgangszustand — "
              "harness/seed_lineage_lab.py laufen lassen, dann noch einmal.")
        if args.take:
            return 3

    # Erst JETZT nach den Kanten fragen: die Konsole antwortet aus dem Lauf,
    # den sie zuletzt gemacht hat. Vor dem Vorlauf waere das der Stand einer
    # frueheren Messung -- und nach einem Test steht die bestaetigte Kante
    # dort auf `unknown`.
    names = lab_names()
    print(f"Labor: dead={names['dead_row']}  confirmed={names['confirmed_row']}")

    # Vorbedingung 6: Suchfilter setzen und stehen lassen.
    cdp.js("(() => { const q = document.getElementById('filter-q');"
           " q.value = 'probate_seedlab';"
           " q.dispatchEvent(new Event('input', {bubbles:true})); return true; })()")
    time.sleep(1.2)
    cdp.js("document.querySelector('.sidenav__item[data-view=\"overview\"]')"
           ".click(); window.scrollTo(0,0); true;")
    time.sleep(0.8)

    T = load_timing()
    write = bool(args.take)

    # Aufnahme startet ERST JETZT: alles davor (Chrome hochfahren, 30 s
    # Vorlauf, Filter setzen) gehoert nicht ins Video. Der Nullpunkt der Uhr
    # ist das erste geschriebene Bild, nicht der Start von ffmpeg -- sonst
    # liegt der Schnitt um Zehntelsekunden daneben.
    grab = None
    if args.record:
        import capture
        title = (cdp.js("document.title") or "Lineage truth bench")
        window = f"{title} - Google Chrome"
        print(f"Aufnahme (fenstergenau): '{window}' -> {args.record}")
        grab, _ = capture.start(ROOT / args.record, window)

    d = Director(cdp)
    d.note(f"devicePixelRatio={d.dpr}  Monitor@({d.mx},{d.my})")
    d.mark("00-lead-in", kind="event")
    time.sleep(args.lead_in)

    # Jeder Abschnitt bekommt seine Dauer, nicht seine Endzeit. Laeuft einer
    # ueber (Seite laedt langsamer), schiebt sich alles nach hinten, statt dem
    # naechsten Abschnitt Zeit wegzunehmen. Wie lang es wirklich wurde, misst
    # der Schnitt hinterher.
    D = {sid: T[sid]["video_s"] for sid in CONSOLE_SEGMENTS}
    seg_01_payoff(d, names, D["01-payoff"])
    seg_02_seeded(d, names, D["02-seeded"])
    seg_03_dead_edge(d, names, D["03-dead-edge"])
    seg_04a_flip_before(d, names, D["04a-flip-before"])
    seg_04b_cut(d, names, D["04b-cut"], write=write)
    if write and getattr(d, "_transcript", None) is not None:
        d._transcript.join(timeout=60)
    seg_transcript(d, "04c-reveal", D["04c-reveal"])
    seg_05_transitions(d, names, D["05-transitions"])
    seg_transcript(d, "06-model", D["06-model"])
    seg_transcript(d, "07-gate", D["07-gate"])
    seg_transcript(d, "07b-mcp", D["07b-mcp"])
    seg_08_close(d, names, D["08-close"])
    d.mark("99-end", kind="event")

    total_s = d.t
    tail_s = 0.0
    if grab is not None:
        import capture
        _t = time.perf_counter()
        capture.stop(grab)
        tail_s = time.perf_counter() - _t

    out = {"mode": "take" if write else "dry-run",
           "lead_in_s": args.lead_in,
           "recording": args.record,
           # `total_s` + `tail_s` sind das, woraus der Schnitt seinen Versatz
           # rechnet: alles, was die Aufnahme laenger ist, lag VOR der ersten
           # Marke. Siehe capture.py.
           "total_s": round(total_s, 3),
           "tail_s": round(tail_s, 3),
           "marks": d.marks}
    (ROOT / args.marks).write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"\nMarken -> {args.marks}   Gesamtlaenge {d.t:.2f} s")

    if not args.keep_chrome and proc:
        proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
