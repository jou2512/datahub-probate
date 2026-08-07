"""Der Korrektur-Modus: aus einem Befund wird ein Vorschlag.

Warum diese Datei existiert: das Register sagt, was nicht stimmt. Damit
daraus eine Handlung wird, braucht es einen Vorschlag mit Beleg, den ein
Mensch bestaetigt -- nicht ein Werkzeug, das den Katalog nach eigenem
Urteil umschreibt.

`writeback.py` bleibt unveraendert; dieses Modul ist ein Aufrufer, kein
zweiter Schreibweg. Und `propose()` bekommt bewusst kein gms und kein
Writeback: was nicht schreiben kann, schreibt auch nicht versehentlich.

Auf `unknown` wird NIE etwas vorgeschlagen. Bei fehlender Datenlage ist
jeder Schreibvorgang ein Schreibvorgang auf Verdacht -- genau der Fehler,
den Schicht 1 behebt.

Messschritt (07.08., `harness/runs/upstream-properties-probe.json`):
`UpstreamLineage.upstreams[].properties` (Map) uebersteht einen echten
Schreib-/Lesezyklus gegen 28080 (`properties_survived: true`, live
gemessen, seeded=true). Deshalb schreibt `mark_dead` kanten-genau auf
`upstreamLineage` mit `properties["probate.dead_since"]`, nicht auf ein
tabellenbezogenes Feld wie `deprecation` -- ein Marker auf der Tabelle
wuerde JEDE Kante als tot ausweisen, nicht nur die gemessene.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass


@dataclass(frozen=True)
class Proposal:
    """Ein Vorschlag traegt IMMER seinen Beleg -- `evidence` hat keinen
    Default, ein Proposal ohne Beleg laesst sich also nicht konstruieren
    (siehe tests/test_correct.py, test_a_proposal_cannot_be_constructed_
    without_evidence).

    `state` (Task-12-Haertung, aus dem Task-11-Review): der ROHE
    Kantenzustand aus dem Register ("dead"/"missing"/"confirmed"), nicht
    nur `kind`. Ohne Default, aus demselben Grund wie `evidence` -- ein
    Vorschlag ohne mitgefuehrten Zustand waere an der Schreibstelle nicht
    gegenprobbar. `apply_proposal` prueft ihn bei `mark_dead` ein zweites
    Mal, unabhaengig vom if/elif in `propose()`."""

    kind: str
    edge_key: str
    target_urn: str
    aspect: str
    evidence: dict
    state: str
    human_summary: str

    def to_json(self) -> dict:
        return {
            "kind": self.kind, "edge": self.edge_key, "target_urn": self.target_urn,
            "aspect": self.aspect, "evidence": self.evidence, "state": self.state,
            "human_summary": self.human_summary,
        }


@dataclass(frozen=True)
class Abstention:
    """Eine bewusste Enthaltung -- KEIN Fehler.

    (Task-12-Review, Fix-Runde 2, Fund 1): die Enthaltungsquote ist die
    Kennzahl, die dieses Produkt verkauft ("das Werkzeug raet nicht, es
    enthaelt sich" -- `CLAUDE.md` diese Projekts). Ein Fall wie "die
    Messung traegt kein Datum" ist ein anderes Ereignis als "dieses
    Proposal wurde manipuliert" oder "die Evidenz ist leer" -- beide waren
    vorher gleichermassen ein `raise ValueError` und damit fuer einen
    Aufrufer ununterscheidbar. Diese Klasse gibt der Enthaltung ein
    eigenes, maschinenlesbares Ergebnis: `apply_proposal` gibt sie
    zurueck (wirft NICHT), ein Aufrufer kann Enthaltungen separat von
    Ablehnungen zaehlen, ohne Exception-Typen zu parsen.
    """

    kind: str  # z.B. "no_measured_dead_since_date" -- maschinenlesbar, stabil
    edge_key: str
    reason: str

    def to_json(self) -> dict:
        return {"abstained": True, "kind": self.kind, "edge": self.edge_key,
                "reason": self.reason}


def propose(ledger: dict) -> list[Proposal]:
    """Liest ein `ledger.py::run()`-Artefakt (bzw. dessen Testform) und
    erzeugt aus jeder nicht-`unknown`-Kante genau einen Vorschlag.

    Signatur bewusst einparametrig (`ledger` allein) -- kein `gms`, kein
    `writeback`: diese Funktion kann strukturell nicht schreiben.

    (Review, CRITICAL 1): `ledger["seeded"]` ist die einzige Stelle im
    Register, die weiss, ob der Katalog dahinter geseedete Demo-Daten
    oder echte Warehouse-Nutzung liefert (`ledger.run()` setzt sie oben
    im Lauf, siehe dortiger Kommentar). Bislang wanderte dieser Wert
    NIRGENDS in einen Vorschlag -- `apply_proposal` schrieb "seeded data"
    als Literal in JEDEN `enrich_doc`-Text, unabhaengig davon, was das
    Register tatsaechlich mass. Heute zufaellig richtig (die einzige
    existierende Ledger-Quelle ist immer geseedet), gegen echten Verkehr
    waere es eine unbelegte Behauptung -- genau die Fehlerklasse, gegen
    die dieses Projekt existiert. `seeded` wird deshalb hier UNVERAENDERT
    durchgereicht (nicht erfunden): fehlt der Schluessel (z.B. in einem
    handgeschriebenen Test-Ledger), ist die Herkunft UNBEKANNT
    (`evidence["seeded"] is None`), nicht "nicht geseedet" -- der
    Unterschied entscheidet an der Schreibstelle, ob ueberhaupt eine
    Herkunfts-Aussage in den Katalogtext darf.
    """
    seeded = ledger.get("seeded")
    out: list[Proposal] = []
    for row in ledger.get("edges", []):
        state, ev = row.get("state"), row.get("evidence") or {}
        tl = row.get("timeline") or {}
        up, down, key = row["upstream"], row["downstream"], row["edge"]

        if state == "missing":
            out.append(Proposal(
                kind="add_edge", edge_key=key, target_urn=down,
                aspect="upstreamLineage", state=state,
                evidence={"query_urns": ev.get("query_urns", []),
                          "cooccurrence_count": ev.get("cooccurrence_count", 0),
                          "direction_evidence": ev.get("direction_evidence", "")},
                human_summary=(
                    f"Kante {key} in {ev.get('cooccurrence_count', 0)} Abfrage(n) beobachtet, "
                    f"aber nicht deklariert. Beleg: {', '.join(ev.get('query_urns', [])) or '-'}. "
                    f"Richtung ist ungerichtet aus Ko-Okkurrenz erschlossen, nicht gemessen."),
            ))
        elif state == "dead":
            out.append(Proposal(
                kind="mark_dead", edge_key=key, target_urn=down,
                aspect="upstreamLineage", state=state,
                evidence={"last_covered_ms": tl.get("last_covered_ms"),
                          "dead_since_days": tl.get("dead_since_days"),
                          "dead_since_is_lower_bound": tl.get("dead_since_is_lower_bound", False),
                          "buckets_checked": ev.get("buckets_checked", 0)},
                human_summary=(
                    f"Kante {key} seit {tl.get('dead_since_days')} Tagen ohne gemessenen "
                    f"Verkehr, geprueft ueber {ev.get('buckets_checked', 0)} Zeitfenster."),
            ))
        elif state == "confirmed":
            out.append(Proposal(
                kind="enrich_doc", edge_key=key, target_urn=down,
                aspect="editableDatasetProperties", state=state,
                evidence={"query_urns": ev.get("query_urns", []),
                          "last_covered_ms": tl.get("last_covered_ms"),
                          "seeded": seeded},
                human_summary=(
                    f"Beobachtete Nutzung von {up} dokumentieren "
                    f"({len(ev.get('query_urns', []))} Abfrage(n))."),
            ))
        # state == "unknown" (oder ein unbekannter Wert): bewusst kein
        # Zweig -- fehlende Datenlage erzeugt keinen Vorschlag.
    return out


# --- Schicht 2: Schreiben -- mergen, nie ersetzen -------------------------
#
# DataHubs eigener sql_parsing_aggregator baut bei JEDEM Lauf eine frische,
# leere Kantenliste und emittiert sie als vollen Aspekt
# (sql_parsing_aggregator.py:1534, selbst nachgelesen im Upstream-Quellcode)
# -- damit verschwinden legitime Kanten, die dieser Lauf nicht gesehen hat.
# Dieses Modul tut das Gegenteil: lesen, mergen, zurueckschreiben.

DEAD_MARKER_KEY = "probate.dead_since"


def _resolve_aspect_before(before: dict | None) -> dict:
    """Der Aspekt-WERT (nicht die Huelle) -- niemals stillschweigend leer.

    (Task-12-Review, Fund IMPORTANT 4): der Aspekt-Wert kommt in zwei
    Formen vor -- gewrappt (`{"value": {...}}`, wie `get_aspect()`
    liefert) oder direkt (`{...}`, die Form, die `writeback.py:79` beim
    Revert manchmal uebergibt: `e["before"].get("value", e["before"])`).
    Die alte `merge_upstreams`-Kette (`(before or {}).get("value") or {}`)
    loeste diese Mehrdeutigkeit NICHT auf: ein `before` ohne `value`-
    Schluessel wurde still zu `{}`, also einer leeren bestehenden Liste --
    derselbe Datenverlust, den dieses Modul verhindern soll, nur eine
    Ebene tiefer und ohne jede Fehlermeldung.

    `before=None` (der Aspekt existiert noch nicht) ist der einzige Fall,
    der ohne Fehler zu `{}` aufgeloest wird. Jede andere Form, aus der
    sich kein `"upstreams"` herleiten laesst, ist mehrdeutig und wird
    ABGELEHNT statt geraten.
    """
    if before is None:
        return {}
    value = before.get("value", before) if isinstance(before, dict) else before
    if not isinstance(value, dict) or "upstreams" not in value:
        raise ValueError(
            "merge_upstreams: 'before' hat eine unbekannte form und kann nicht "
            f"sicher gemergt werden (weder value.upstreams noch upstreams direkt "
            f"vorhanden): {before!r}"
        )
    return value


def merge_upstreams(
    before: dict | None,
    add: list[dict] = (),
    drop: list[str] = (),
    mark_dead: dict[str, str] | None = None,
) -> dict:
    """Bestehende Kanten bleiben. Immer -- und das gilt fuer JEDEN
    Top-Level-Schluessel des Aspekts, nicht nur `upstreams`.

    (Task-12-Review, Fund CRITICAL 1): `UpstreamLineageClass` traegt auch
    `fineGrainedLineages` (spaltengenaue Lineage, von dbt/BigQuery/
    Snowflake/Looker/Spark & Co. emittiert). Die urspruengliche Fassung
    las nur `value.upstreams` und gab `{"upstreams": [...]}` zurueck --
    genau das, was dieses Modul an DataHubs eigenem Aggregator kritisiert
    (frischer, leerer Aspekt ersetzt den ganzen bestehenden), nur eine
    Ebene tiefer: jeder unbekannte Top-Level-Schluessel wurde bei JEDEM
    Schreibvorgang stillschweigend geloescht. Jetzt wird der komplette
    aufgeloeste Aspekt-Wert als Basis genommen und nur `upstreams` ersetzt
    (vgl. DataHubs eigenes `incremental_lineage_helper.py`, das beide
    Felder durchreicht).

    `before` ist die rohe `get_aspect()`-Antwort (oder eine unverpackte
    Form, siehe `_resolve_aspect_before`) bzw. `None`, wenn der Aspekt noch
    nicht existiert. Reihenfolge bewusst DROP-vor-ADD-vor-MARK_DEAD (so
    steht es im Code; eine fruehere Fassung dieses Docstrings nannte die
    falsche Reihenfolge -- Task-12-Review, Minor 6): eine Kante kann in
    derselben Runde entfernt, neu hinzugefuegt und markiert werden
    (theoretisch widerspruechlich, aber die Funktion soll dabei nicht
    raten, welche Absicht Vorrang hat -- sie tut schlicht alle drei, in
    dieser Reihenfolge).
    """
    resolved = _resolve_aspect_before(before)
    existing = list(resolved.get("upstreams") or [])
    drop_set = set(drop)
    out = [u for u in existing if u.get("dataset") not in drop_set]
    have = {u.get("dataset") for u in out}
    for u in add:
        if u.get("dataset") not in have:
            out.append(dict(u))
            have.add(u.get("dataset"))
    if mark_dead:
        marked = []
        for u in out:
            if u.get("dataset") in mark_dead:
                props = dict(u.get("properties") or {})
                props[DEAD_MARKER_KEY] = mark_dead[u["dataset"]]
                marked.append({**u, "properties": props})
            else:
                marked.append(u)
        out = marked
    return {**resolved, "upstreams": out}


def _iso_day(ms: int | None) -> str:
    if ms is None:
        return "unbekannt"
    return _dt.datetime.fromtimestamp(ms / 1000, _dt.timezone.utc).date().isoformat()


def _dead_since_iso(evidence: dict) -> str | None:
    """Das GEMESSENE Sterbedatum -- niemals der Moment des Schreibens.
    `None`, wenn keins vorliegt (kein Fehler -- siehe `Abstention`).

    (Task-12-Review, Fund IMPORTANT 2): `now_ms` ist der Zeitpunkt des
    Schreibvorgangs, nicht der Zeitpunkt, seit dem die Kante tot ist. Die
    Evidenz traegt das bereits (`last_covered_ms`, aus DERSELBEN Messung
    wie `dead_since_days`, siehe `ledger.Timeline`) -- dieses Datum wird
    geschrieben, "heute" nie.

    Fehlt `last_covered_ms` (das passiert, wenn im GESAMTEN geprueften
    Fenster nie Verkehr gemessen wurde -- `ledger.Timeline.dead_since()`
    liefert dann nur eine Untergrenze ab dem AELTESTEN Bucket,
    `dead_since_is_lower_bound=True`), gibt es kein exaktes Datum zu
    belegen. Ein `now_ms`-basierter Ersatz waere exakt die unbelegte
    Behauptung, die dieser Fund verbietet.

    Fix-Runde 2 (Opus-Re-Review, Fund 1): das war urspruenglich ein
    `raise ValueError`, ununterscheidbar von einer echten Ablehnung
    (manipuliertes Proposal, kaputte Evidenz). Der Reviewer weist zu
    recht darauf hin, dass die Enthaltungsquote die Kennzahl ist, die
    dieses Produkt verkauft ("das Werkzeug raet nicht, es enthaelt sich")
    -- ein Fehler in derselben Kategorie wie ein Bug wuerde diese Faelle
    aus der Zaehlung verlieren. Also: `None` ist hier ein legitimer
    Rueckgabewert, keine Fehlermeldung. `apply_proposal` macht daraus eine
    `Abstention`, nicht eine Exception.
    """
    last_covered_ms = evidence.get("last_covered_ms")
    if last_covered_ms is None:
        return None
    return _iso_day(last_covered_ms)


def _resolve_editable_props_before(before: dict | None) -> dict:
    """Wie `_resolve_aspect_before`, aber ohne `"upstreams"`-Pflichtfeld:
    `editableDatasetProperties` hat kein Feld, dessen Anwesenheit die
    gewrappte von der entpackten Form unterscheidet -- ein leerer Aspekt
    (`{}`) ist hier gueltig (Dataset ohne jede kuratierte Property).
    Deshalb nur entpacken (`value`-Schluessel, falls vorhanden), nie gegen
    einen Pflicht-Schluessel pruefen.
    """
    if before is None:
        return {}
    if not isinstance(before, dict):
        raise ValueError(
            f"enrich_doc: 'before' hat eine unbekannte form: {before!r}"
        )
    value = before.get("value", before)
    if not isinstance(value, dict):
        raise ValueError(
            f"enrich_doc: 'before.value' hat eine unbekannte form: {before!r}"
        )
    return value


_ENRICH_DOC_TAG = "[probate:enrich_doc]"
# EINGEFROREN ab jetzt (Review, Fixrunde 2): dieser Wortlaut aendert sich nie
# wieder. Jede kuenftige Formulierungsaenderung des Notiztexts bleibt hinter
# demselben Tag -- sonst wiederholt sich genau der Fund unten in einer
# weiteren Runde.
_LEGACY_ENRICH_DOC_PREFIX = "probate:"
# Deckt jeden Block ab, den eine Fassung DIESES Moduls VOR der Einfuehrung
# des Tags geschrieben hat -- jede historische Notiz begann mit exakt diesem
# Praefix (siehe Docstring unten, Review Fixrunde 2 fuer das WARUM).


def merge_editable_description(before: dict | None, note: str) -> dict:
    """Haengt eine probate-Notiz an -- ueberschreibt NIE eine bestehende
    Beschreibung, und wird bei wiederholter Anwendung nicht laenger.

    **Warum dieses Feld** (`editableDatasetProperties.description`, nicht
    ein eigenes probate-Feld): es ist im DataHub-UI die kuratierte
    Beschreibung, die Menschen tatsaechlich lesen. Ein verstecktes Feld
    (z.B. `customProperties["probate.note"]`) waere "sicherer" im Sinn
    von nie-vermischt, aber fuer den eigentlichen Zweck -- beobachtete
    Nutzung SICHTBAR dokumentieren -- nutzlos.

    **Warum ausschliesslich anhaengend** (nie ersetzend): es gibt auf
    diesem Aspekt kein zweites, probate-exklusives Feld (anders als
    `upstreamLineage.upstreams[].properties["probate.dead_since"]` bei
    `mark_dead`, Task 12). Eine bestehende, von einem Menschen
    geschriebene Beschreibung zu ersetzen waere dieselbe Fehlerklasse wie
    das stille Loeschen von `fineGrainedLineages` in `merge_upstreams`
    (Task-12-Review, CRITICAL 1) -- nur auf einem Aspekt, den Menschen
    lesen statt nur BI-Tools. Anhaengen ist die einzige Operation, die
    das strukturell ausschliesst.

    (Review, IMPORTANT 2): eine Korrektur-Runde laeuft wiederholt gegen
    denselben Ledger -- ohne Erkennung eines bestehenden probate-Blocks
    haengt jeder Lauf einen weiteren, textgleichen Absatz an, unbegrenzt.
    `merge_upstreams` verhindert dieselbe Fehlerklasse fuer Kanten
    (`if u.get("dataset") not in have`) -- hier ist der Wächter
    `_ENRICH_DOC_TAG`, ein Marker, den NUR probate schreibt: alles VOR
    dem Marker ist garantiert menschlicher Text und bleibt stehen, alles
    AB dem Marker ist der letzte probate-Block und wird durch den
    aktuellen ERSETZT (nicht uebersprungen) -- ein Re-Lauf mit neuer
    Evidenz (mehr Abfragen, spaeteres Datum) soll den Text auffrischen,
    nicht auf einer veralteten Fassung sitzen bleiben.

    (Review, Fixrunde 2, IMPORTANT -- lauffaehig gefunden): der erste
    Fix erkannte NUR den eigenen, aktuellen `_ENRICH_DOC_TAG`. Ein Block,
    den eine FRUEHERE Fassung dieser Funktion geschrieben hat -- z.B. das
    literale Vorher-Format `"probate: observed usage..."`, das genau
    dieser Task-13-Fix selbst ersetzt hat -- war fuer den Detektor
    unsichtbar, zaehlte als menschlicher Text, und ein ZWEITER Block
    wurde darunter angehaengt. Betrifft nicht nur hypothetische
    Zukunftsversionen: der eigene Fix-Wortlaut dieser Funktion war beim
    ersten Versuch eine Instanz genau der Klasse, die sie nicht faengt --
    und ein Kunde, der das Werkzeug upgraded, waere derselbe Fall.

    Deshalb zwei Marker statt einem, und die FRUEHESTE Fundstelle
    entscheidet: `_ENRICH_DOC_TAG` ist ab jetzt eingefroren (sein
    Wortlaut aendert sich nie wieder -- jede kuenftige Notiz-Formulierung
    bleibt hinter demselben Tag), `_LEGACY_ENRICH_DOC_PREFIX` ("probate:",
    ohne Klammern) faengt zusaetzlich JEDEN Block, den eine Fassung
    dieses Moduls vor der Tag-Einfuehrung geschrieben hat -- jede
    historische Notiz begann mit exakt diesem Praefix. Eine Alternative
    waere gewesen, den Marker nur fuer zukuenftige Versionen einzufrieren
    und alte Bloecke als verlorenen Fall hinzunehmen -- verworfen, weil
    das genau die zwei konkreten Faelle nicht schliesst, die der Review
    nennt: Bloecke, die heute Nacht schon im Demo-Katalog liegen
    koennten, und ein realer Kunden-Upgrade. Risiko der Wahl: ein Mensch,
    dessen eigener Text zufaellig mit "probate:" beginnt, wird ab dort
    faelschlich als probate-Block behandelt -- kein Escape-Mechanismus
    dagegen. Bewusst in Kauf genommen: eine falsch erkannte Grenze
    verliert im schlimmsten Fall einen Satz Kontext, eine NICHT erkannte
    alte Notiz haeuft sich dagegen bei jedem weiteren Korrektur-Lauf
    weiter an -- das unbegrenzte Wachstum ist der schlimmere Fehler.

    Jeder andere Top-Level-Schluessel des Aspekts (z.B.
    `customProperties`) bleibt unangetastet -- derselbe Grundsatz wie
    `merge_upstreams`: der ganze aufgeloeste Wert ist die Basis, nicht
    ein frisch gebautes `{"description": ...}`.
    """
    resolved = _resolve_editable_props_before(before)
    old = resolved.get("description") or ""
    positions = [
        pos for pos in (old.find(_ENRICH_DOC_TAG), old.find(_LEGACY_ENRICH_DOC_PREFIX))
        if pos != -1
    ]
    marker = min(positions) if positions else -1
    human_part = old[:marker].rstrip() if marker != -1 else old.strip()
    text = f"{human_part}\n\n{note}" if human_part else note
    return {**resolved, "description": text}


def _has_real_entries(items) -> bool:
    """`["", "  "]` ist eine nicht-leere Liste, aber keine Substanz
    (Task-12-Review, Minor 9) -- mindestens ein Eintrag muss, getrimmt,
    tatsaechlich Zeichen enthalten."""
    return any((x or "").strip() for x in items)


def _require_substantive_evidence(p: Proposal) -> None:
    """`evidence={}` laesst sich konstruieren (Task-11-Review, Fund 1) --
    formal belegt, inhaltlich leer. Ein Proposal darf entstehen und
    angezeigt werden; angewandt werden darf nur eines, dessen Beleg fuer
    SEINE Vorschlagsart tatsaechlich traegt. Pro Art eine eigene
    Substanz-Definition -- "irgendein Schluessel ist gesetzt" waere selbst
    wieder nur eine Formalitaet, keine Substanz.
    """
    if p.kind == "add_edge":
        query_urns = p.evidence.get("query_urns") or []
        cooccurrence_count = p.evidence.get("cooccurrence_count") or 0
        if not _has_real_entries(query_urns) or cooccurrence_count <= 0:
            raise ValueError(
                f"vorschlag {p.edge_key} ({p.kind}) hat keinen tragfaehigen beleg -- "
                f"query_urns={query_urns!r} cooccurrence_count={cooccurrence_count!r} "
                "-- wird nicht geschrieben"
            )
    elif p.kind == "mark_dead":
        dead_since_days = p.evidence.get("dead_since_days")
        buckets_checked = p.evidence.get("buckets_checked") or 0
        if dead_since_days is None or dead_since_days < 0 or buckets_checked <= 0:
            raise ValueError(
                f"vorschlag {p.edge_key} ({p.kind}) hat keinen tragfaehigen beleg -- "
                f"dead_since_days={dead_since_days!r} buckets_checked={buckets_checked!r} "
                "-- wird nicht geschrieben"
            )
    elif p.kind == "enrich_doc":
        query_urns = p.evidence.get("query_urns") or []
        if not _has_real_entries(query_urns):
            raise ValueError(
                f"vorschlag {p.edge_key} ({p.kind}) hat keinen tragfaehigen beleg -- "
                f"query_urns={query_urns!r} -- wird nicht geschrieben"
            )
    else:
        raise ValueError(f"unbekannte vorschlagsart fuer beleg-pruefung: {p.kind}")


def _require_dead_state(state: str | None) -> None:
    """Zweite, von `propose()` UNABHAENGIGE Sperre gegen die
    unknown-als-tot-Verwechslung (Task-11-Review, Fund 2).

    Das if/elif in `propose()` ist eine Allowlist, aber eine Allowlist an
    einer einzigen Stelle im Code ist kein versiegelter Pfad -- ein
    kuenftiger Refactor dort koennte sie leise aufweichen. Diese Funktion
    prueft an der SCHREIBSTELLE ein zweites Mal, gegen den Zustand, den
    der Vorschlag selbst mitfuehrt (`Proposal.state`), und akzeptiert
    ausschliesslich den exakten String "dead". "unknown", "confirmed",
    "missing", `None` und jede Gross-/Kleinschreibungs-Variante werden
    abgelehnt.
    """
    if state != "dead":
        raise ValueError(
            f"dead-markierung verweigert: kantenzustand ist {state!r}, nicht 'dead'"
        )


def apply_proposal(
    wb, p: Proposal,
    actor: str = "urn:li:corpuser:__datahub_system",
    now_ms: int = 0,
):
    """Wendet EINEN bestaetigten Vorschlag an -- ueber writeback.py.

    Nie direkt ueber gms: writeback sichert den Vorher-Zustand ins
    Journal, und nur dadurch deckt `probate revert` auch diese
    Schreibvorgaenge. `wb.aspect()` gibt intern eine LISTE an
    gms.upsert() (Falle 1) -- ein eigener Weg wuerde das umgehen.

    Haertungen aus dem Task-11- und dem Task-12-Review laufen VOR jedem
    Schreiben: ein Vorschlag ohne tragfaehigen Beleg, mit einer
    edge_key/target_urn-Diskrepanz oder mit einem `mark_dead` auf einer
    nicht-toten bzw. nicht-existenten Kante scheitert hier laut, bevor
    `wb.aspect()` ueberhaupt aufgerufen wird.

    Rueckgabe ist NICHT immer ein `WriteResult`: fehlt bei `mark_dead` ein
    gemessenes Sterbedatum, gibt diese Funktion eine `Abstention` zurueck
    (siehe deren Docstring, Fix-Runde 2, Fund 1) -- eine bewusste
    Enthaltung, kein Fehler. Eine `ValueError` bleibt fuer echte
    Ablehnungen reserviert (kaputte/leere Evidenz, manipuliertes
    Proposal, Kante nicht in der bestehenden Lineage) -- ein Aufrufer
    kann beide Ergebnisarten damit strukturell auseinanderhalten, statt
    Fehlertexte zu parsen.
    """
    _require_substantive_evidence(p)

    # Task-12-Review, Minor 8: edge_key traegt die Downstream-URN ein
    # zweites Mal (als Teil von "upstream->downstream"). Ohne diesen
    # Abgleich koennte ein handkonstruiertes/manipuliertes Proposal eine
    # beliebige Upstream-URN auf ein beliebiges Ziel-Dataset schreiben --
    # `target_urn` wuerde einfach geglaubt, `edge_key` nie geprueft.
    try:
        upstream, edge_downstream = p.edge_key.split("->", 1)
    except ValueError:
        raise ValueError(f"edge_key hat nicht die form 'upstream->downstream': {p.edge_key!r}")
    if edge_downstream != p.target_urn:
        raise ValueError(
            f"edge_key/target_urn stimmen nicht ueberein: edge_key nennt downstream="
            f"{edge_downstream!r}, target_urn={p.target_urn!r} -- wird nicht geschrieben"
        )

    if p.kind == "add_edge":
        before = wb.gms.get_aspect("dataset", p.target_urn, "upstreamLineage") \
            if hasattr(wb, "gms") else None
        value = merge_upstreams(before, add=[{
            "dataset": upstream, "type": "TRANSFORMED",
            "auditStamp": {"time": now_ms, "actor": actor},
            "properties": {"probate.evidence": ",".join(p.evidence.get("query_urns", [])),
                           "probate.direction": p.evidence.get("direction_evidence", "")},
        }])
        return wb.aspect("dataset", p.target_urn, "upstreamLineage", value)

    if p.kind == "mark_dead":
        _require_dead_state(p.state)
        dead_since = _dead_since_iso(p.evidence)
        if dead_since is None:
            # Fix-Runde 2, Fund 1: KEINE Exception -- eine Enthaltung ist
            # kein Fehler, sondern das, wofuer dieses Produkt antritt.
            # Kein `before`-Fetch noetig: ohne Datum gibt es nichts zu
            # schreiben, also auch nichts zu lesen.
            return Abstention(
                kind="no_measured_dead_since_date", edge_key=p.edge_key,
                reason=(
                    "last_covered_ms fehlt in der evidenz -- dead_since_days waere hier "
                    "nur eine untergrenze ab dem aeltesten geprueften bucket, kein "
                    "gemessenes datum. das werkzeug enthaelt sich, statt zu schaetzen."
                ),
            )
        before = wb.gms.get_aspect("dataset", p.target_urn, "upstreamLineage") \
            if hasattr(wb, "gms") else None

        # Task-12-Review, Fund IMPORTANT 3: zwei stille Fehlschlaege
        # verhindern. (a) Existiert ueberhaupt kein Aspekt, waere
        # `merge_upstreams(None, mark_dead=...)` ein leeres `{"upstreams":
        # []}` -- eine nie gemessene Behauptung "dieses Dataset hat keine
        # Upstreams". (b) Ist der Upstream nicht in der bestehenden Liste,
        # schriebe `merge_upstreams` die IDENTISCHE Liste zurueck, mit
        # `applied=True` und ohne jeden Marker -- der Mensch bestaetigt
        # eine Tot-Markierung, und nichts passiert. Beide Faelle sind
        # dieselbe Wurzel: eine `dead`-Markierung ohne die deklarierte
        # Kante, auf die sie sich bezieht, ist sinnlos -- verweigern statt
        # still nichts (oder etwas Erfundenes) zu tun.
        resolved = _resolve_aspect_before(before)
        existing_urns = {u.get("dataset") for u in resolved.get("upstreams") or []}
        if upstream not in existing_urns:
            raise ValueError(
                f"dead-markierung verweigert: {upstream!r} steht nicht in der bestehenden "
                f"upstreamLineage von {p.target_urn!r} -- ohne bestehenden eintrag waere das "
                "entweder ein stiller kein-op oder eine nie gemessene leere upstreams-liste"
            )

        value = merge_upstreams(before, mark_dead={upstream: dead_since})
        return wb.aspect("dataset", p.target_urn, "upstreamLineage", value)

    if p.kind == "enrich_doc":
        # Kein Zustands-Gate wie `_require_dead_state`: `propose()` erzeugt
        # `enrich_doc` ausschliesslich fuer `state == "confirmed"`, und
        # anders als bei `mark_dead` gibt es keinen destruktiven Nebeneffekt
        # bei einem falschen Zustand -- es wird angehaengt, nichts geloescht
        # oder als tot markiert. `_require_substantive_evidence` (oben
        # bereits gelaufen) verweigert ohnehin, wenn `query_urns` leer ist.

        # (Review, IMPORTANT 3): wie `mark_dead` -- ohne gemessenes Datum
        # waere die "last covered"-Aussage im Katalogtext eine Behauptung
        # ohne Beleg (`_iso_day(None)` gibt bislang das deutsche Wort
        # "unbekannt" in einen sonst englischen Satz zurueck -- kein
        # Enthaltungs-Signal, sondern eine falsche Aussage, die trotzdem
        # geschrieben wurde). Dieselbe Enthaltungsklasse wie `mark_dead`,
        # kein zweiter `before`-Fetch noetig, bevor eine Enthaltung feststeht.
        last_covered_ms = p.evidence.get("last_covered_ms")
        if last_covered_ms is None:
            return Abstention(
                kind="no_measured_last_covered_date", edge_key=p.edge_key,
                reason=(
                    "last_covered_ms fehlt in der evidenz -- eine 'zuletzt "
                    "beobachtet'-aussage waere ohne gemessenes datum unbelegt. "
                    "das werkzeug enthaelt sich, statt zu schaetzen."
                ),
            )

        # (Review, CRITICAL 1): die Herkunfts-Aussage ("seeded data") kommt
        # AUS der Evidenz (propose() reicht `ledger["seeded"]` durch, siehe
        # dort), nie als Literal. Unbekannte Herkunft (Schluessel fehlt
        # oder `None`) behauptet NICHTS -- weder "seeded" noch "real": beides
        # waere eine unbelegte Aussage im selben Sinn wie ein erfundenes
        # Datum. Nur `seeded is True` (GEMESSEN, nicht angenommen) darf den
        # Zusatz "seeded data" tragen.
        seeded = p.evidence.get("seeded")
        source_clause = ("source: DataHub usage statistics, seeded data"
                          if seeded is True else "source: DataHub usage statistics")

        before = wb.gms.get_aspect("dataset", p.target_urn, "editableDatasetProperties") \
            if hasattr(wb, "gms") else None
        n = len(p.evidence.get("query_urns", []))
        qword = "query" if n == 1 else "queries"
        note = (
            f"{_ENRICH_DOC_TAG} observed usage from {upstream} in {n} measured "
            f"{qword}, last covered {_iso_day(last_covered_ms)} ({source_clause})."
        )
        value = merge_editable_description(before, note)
        return wb.aspect("dataset", p.target_urn, "editableDatasetProperties", value)

    # (Review, MINOR 5): kein `raise` hier -- unerreichbar. Jedes `p.kind`
    # ausserhalb von add_edge/mark_dead/enrich_doc scheitert bereits ganz
    # oben an `_require_substantive_evidence` (deren eigener `else`-Zweig),
    # bevor diese Funktion ueberhaupt bis hierher kommt. Ein zweiter,
    # toter `raise` mit einer nie gezeigten Nachricht waere genau das
    # Gegenteil von auditierbar -- ein Test, der ihn zu pruefen scheint,
    # prueft in Wahrheit den `else`-Zweig oben (siehe
    # test_an_unknown_proposal_kind_is_loud).


def remove_edge(wb, upstream: str, downstream: str, now_ms: int = 0):
    """Nimmt EINE deklarierte Kante weg -- nur auf ausdruecklichen Zuruf.

    Kein Vorschlag erzeugt das automatisch: `propose()` kennt nur
    `add_edge`/`mark_dead`/`enrich_doc`, alle additiv oder markierend.
    Eine Kante zu entfernen ist die einzige nicht-additive Handlung in
    diesem Modul, und sie passiert nur, wenn ein Mensch sie ausserhalb
    des Vorschlags-Flusses ausloest -- z.B. weil eine Kante nachweislich
    falsch deklariert war, nicht bloss tot. Das Journal deckt sie
    trotzdem (`wb.aspect()` sichert den Vorher-Zustand, `revert_all()`
    rollt sie wie jeden anderen Schreibvorgang zurueck).

    (Review, IMPORTANT 4): reproduzierte urspruenglich BEIDE Fehlschlaege,
    die Task 12 fuer `mark_dead` bereits behoben hatte (siehe die
    identische Begruendung dort, `IMPORTANT 3`). (a) Kein Aspekt
    vorhanden -> `merge_upstreams(None, drop=[...])` haette ein leeres
    `{"upstreams": []}` GESCHRIEBEN -- eine nie gemessene Behauptung
    "dieses Dataset hat keine Upstreams", nur weil jemand eine Kante
    entfernen wollte, die es dort gar nicht gab. (b) Der Upstream steht
    gar nicht in der bestehenden Liste -> `merge_upstreams` haette die
    IDENTISCHE Liste zurueckgeschrieben, `applied=True`, ohne jedes
    Signal, dass nichts passiert ist. Dieselbe Sperre wie bei `mark_dead`
    (`_resolve_aspect_before` + Mitgliedschafts-Check), auf Entfernen
    statt Markieren angewandt: beide Faelle verweigern jetzt laut, bevor
    `wb.aspect()` ueberhaupt aufgerufen wird.

    `now_ms` wird bewusst entgegengenommen, aber hier nicht verwendet:
    ein Drop hinterlaesst keinen Zeitstempel auf der Kante (es gibt nach
    dem Entfernen keine Kante mehr, auf der einer stehen koennte) --
    der Parameter haelt die Signatur symmetrisch zu `apply_proposal`
    und dem Journal-Zeitstempel, den `writeback.py` beim Revert nutzt.
    """
    before = wb.gms.get_aspect("dataset", downstream, "upstreamLineage")
    if before is None:
        raise ValueError(
            f"kante entfernen verweigert: {downstream!r} hat ueberhaupt keinen "
            "upstreamLineage-aspekt -- ohne bestehenden aspekt waere ein "
            "schreibvorgang eine nie gemessene leere upstreams-liste"
        )
    resolved = _resolve_aspect_before(before)
    existing_urns = {u.get("dataset") for u in resolved.get("upstreams") or []}
    if upstream not in existing_urns:
        raise ValueError(
            f"kante entfernen verweigert: {upstream!r} steht nicht in der bestehenden "
            f"upstreamLineage von {downstream!r} -- ohne bestehenden eintrag waere das "
            "ein stiller kein-op, der applied=True meldet, ohne etwas zu tun"
        )
    value = merge_upstreams(before, drop=[upstream])
    return wb.aspect("dataset", downstream, "upstreamLineage", value)
