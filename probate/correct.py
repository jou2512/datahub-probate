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
    """
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
                          "last_covered_ms": tl.get("last_covered_ms")},
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


def merge_editable_description(before: dict | None, note: str) -> dict:
    """Haengt eine probate-Notiz an -- ueberschreibt NIE eine bestehende
    Beschreibung.

    `editableDatasetProperties.description` ist im DataHub-UI die
    kuratierte, von Menschen geschriebene Beschreibung. Anders als
    `upstreamLineage.upstreams[].properties` (Task 12, `mark_dead`) gibt
    es auf diesem Aspekt kein separates Feld, das probate exklusiv
    gehoert -- also ist Anhaengen an `description`, niemals Ersetzen, die
    einzige Operation, die menschliche Dokumentation nicht zerstoert.
    Ein Klobbern der Beschreibung waere dieselbe Fehlerklasse wie das
    stille Loeschen von `fineGrainedLineages` in `merge_upstreams`
    (Task-12-Review, CRITICAL 1) -- nur auf einem Aspekt, den Menschen
    tatsaechlich lesen.

    Jeder andere Top-Level-Schluessel des Aspekts (z.B.
    `customProperties`) bleibt unangetastet -- derselbe Grundsatz wie
    `merge_upstreams`: der ganze aufgeloeste Wert ist die Basis, nicht
    ein frisch gebautes `{"description": ...}`.
    """
    resolved = _resolve_editable_props_before(before)
    old = (resolved.get("description") or "").strip()
    text = f"{old}\n\n{note}" if old else note
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
        before = wb.gms.get_aspect("dataset", p.target_urn, "editableDatasetProperties") \
            if hasattr(wb, "gms") else None
        n = len(p.evidence.get("query_urns", []))
        qword = "query" if n == 1 else "queries"
        note = (
            f"probate: observed usage from {upstream} in {n} measured "
            f"{qword}, last covered {_iso_day(p.evidence.get('last_covered_ms'))} "
            "(source: DataHub usage statistics, seeded data)."
        )
        value = merge_editable_description(before, note)
        return wb.aspect("dataset", p.target_urn, "editableDatasetProperties", value)

    raise ValueError(f"unbekannte vorschlagsart: {p.kind}")


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

    `now_ms` wird bewusst entgegengenommen, aber hier nicht verwendet:
    ein Drop hinterlaesst keinen Zeitstempel auf der Kante (es gibt nach
    dem Entfernen keine Kante mehr, auf der einer stehen koennte) --
    der Parameter haelt die Signatur symmetrisch zu `apply_proposal`
    und dem Journal-Zeitstempel, den `writeback.py` beim Revert nutzt.
    """
    before = wb.gms.get_aspect("dataset", downstream, "upstreamLineage")
    value = merge_upstreams(before, drop=[upstream])
    return wb.aspect("dataset", downstream, "upstreamLineage", value)
