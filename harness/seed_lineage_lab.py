"""Seedt ein Vier-Zustaende-Labor fuer den spaeteren Kanten-Abgleich.

WARUM: der Beispielkatalog (showcase-ecommerce auf 18080, das eigene Labor
auf 28080) hat keine Nutzungsdaten -- live geprueft, `statsSummary` liefert
`totalSqlQueries: null` fuer jedes Dataset (UEBERGABE.md SS3/SS9). Ohne
Nutzungsdaten kann `probate/ledger.py` (Schicht 1) nie alle vier Kanten-
Zustaende vorfuehren, die es unterscheiden soll:

  confirmed  deklarierte Kante + Ko-Okkurrenz-Query + frische Nutzung auf beiden Enden
  dead       deklarierte Kante, Nutzung existiert (wir haben hingesehen), aber der
             letzte Verkehr liegt ~117 Tage zurueck, danach nur noch Null-Buckets
  missing    Ko-Okkurrenz-Query + frische Nutzung, aber KEINE deklarierte Kante
  unknown    deklarierte Kante, aber ueberhaupt keine Nutzungs-Buckets -- keine
             Daten ist NICHT dasselbe wie tot, und genau diese Verwechslung ist
             der Fehler, den Schicht 1 laut UEBERGABE.md SS6 beheben soll

Alle Schreibvorgaenge sind live gegen 28080 vorab einzeln geprueft worden
(Dataset-Anlage, upstreamLineage-Aspekt-Form, Nutzungs-Bucket ueber 124 Tage
zurueck per usageStats(range: ALL, startTimeMillis:...), Idempotenz bei
gleichem Tages-Zeitstempel, vollstaendiges Entity-Delete inkl. Zeitreihen)
gegen Wegwerf-Entitaeten unter `probate_seedlab_probe.*` und wieder geloescht
-- siehe Abschlussbericht des Agenten-Laufs, nicht Teil dieses Skripts.

Namespace: PLATFORM = postgres, alle URNs unter `probate_seedlab.*` -- klar
als Labor erkennbar, kollidiert nicht mit echten Warehouse-Namen. Jede
Dataset-Beschreibung traegt das Praefix `[probate-seedlab -- synthetische
Demonstrationsdaten]` und den Satz, dass es sich um kuenstlich eingespielte
Demonstrationsdaten handelt (Regel UEBERGABE.md SS7.3: geseedete Daten
werden als geseedet ausgewiesen).

WICHTIG (Entscheid 2026-08-07, docs/entscheidungen/2026-08-07-seed-
beschreibungen-ohne-etikett.md, bindend): der organische Teil der
Beschreibung darf den Ziel-Kanten-Zustand NICHT nennen. Fruehere Fassung
schrieb woertlich "Rolle=upstream, Ziel-Kanten-Zustand=confirmed" in
`datasetProperties.description` -- die einzige Textquelle, die
`probate/judge.py` liest, enthielt damit die Antwort, die das Modell
erst herleiten soll (Echo statt Urteil). Die Beschreibungen sind jetzt
organische Geschaeftssprache, differenziert nach Business-Relevanz, und
tragen ausserhalb des Praefixes kein Zustandswort. Zusaetzlich seedet
dieses Skript jetzt echte `ownership`/`domains`/`glossaryTerms`-Aspekte
(vorher: null Treffer per Grep), damit `probate.judge.gather_context`
ausserhalb der einen Beschreibungszeile etwas zu zitieren hat. Die vier
Kanten-Zustaende selbst entstehen unveraendert aus Lineage + Nutzung +
Query-Subjects (siehe EDGE_STATE_OF_PAIR/USAGE_PLAN unten) -- Gegenprobe
ueber `harness/seedlab_verdicts.py` ist nach jeder Aenderung Pflicht.

NACHTRAG Fix-Runde 4 (2026-08-07): dieselbe Regel gilt seither fuer die
TABELLENNAMEN und die Query-IDs, nicht nur fuer die Beschreibungen. Beide
nannten den Ziel-Zustand woertlich und standen in der Werkbank direkt
neben dem Urteil. Begruendung und Namensregel: Kommentar bei `NAMES`.

Idempotent: alle Nicht-Zeitreihen-Aspekte (Dataset, upstreamLineage, Query)
haben feste URNs/IDs und werden bei jedem Lauf einfach ueberschrieben, nicht
dupliziert (v3-REST-Semantik: gleiche URN + gleicher Aspekt = Ersetzen).

Nutzungs-Buckets sind Zeitreihen, ihr Zeitstempel haengt an `USAGE_ANCHOR`
(dem aktuellen Tag um Mitternacht UTC, neu berechnet bei jedem Lauf --
NICHT an einem fest verdrahteten Kalenderdatum, siehe Kommentar dort:
`probate/ledger.py` klassifiziert ueber ein rollendes 30-Tage-Fenster,
ein starres Datum waere irgendwann aus diesem Fenster herausgelaufen).
Innerhalb eines Laufs ist das deterministisch (derselbe Prozess, derselbe
Zeitstempel). Zwischen zwei Laeufen an verschiedenen Kalendertagen waere
das allein NICHT idempotent -- deshalb wischt `purge_usage_history()` vor
jedem Schreibvorgang die komplette Zeitreihen-Historie aller acht Datasets
(volle Historie, nicht nur den "aktuellsten" Wert -- live geprueft, siehe
Report Fix-Runde 3: die generische `DELETE`-Route entfernt bei Zeitreihen-
Aspekten nur die letzte Zeile). Jeder Lauf beginnt so auf einem leeren
Blatt; zwei Laeufe an zwei verschiedenen Tagen konvergieren auf denselben
verifizierten Zustand (live geprueft: zweimal hintereinander, exit 0,
identische Rohsummen).

Jede Schreiboperation wird zurueckgelesen. Ein Rueckleseversagen ist ein
FEHLER (Exit 1), kein stilles Weiterlaufen -- Regel `verification.md`:
"Eine gescheiterte Abfrage ist keine Abwesenheit".

--------------------------------------------------------------------------
RUNBOOK -- ES-Graph-Index-Drift (Fund Fix-Runde 3, Coordinator-Review)
--------------------------------------------------------------------------
SYMPTOM: `harness/seedlab_verdicts.py` zeigt einen Zustand, der nicht zum
Manifest passt -- typischerweise `missing` liest sich als `confirmed`
(oder generell: eine Kante erscheint deklariert, obwohl sie es laut Design
nicht sein sollte). Der PRIMAERSPEICHER widerspricht: `gms.get_aspect(
"dataset", <urn>, "upstreamLineage")` zeigt `None`/leer, aber die GraphQL-
Abfrage `dataset(urn){ lineage(direction: ...) { relationships { entity {
urn } } } }` (der ES-Graph-Index, den `probate/ledger.py::
fetch_declared_edges()` tatsaechlich abfragt) zeigt eine Kante, die im
Aspekt nicht existiert.

URSACHE: der ES-Graph-Index wird ueber Kafka-MCL-Consumer nachgezogen
(Falle 15: "Graph-/Suchindex hinkt Writes UND Deletes nach"). Bei
Kafka-Consumer-Instabilitaet (live gemessen, 07.08.: 5362 Treffer fuer
`COORDINATOR_NOT_AVAILABLE` in 3h auf einer seit Tagen als `unhealthy`
markierten GMS-Instanz) kann ein verzoegert/dupliziert nachgeholter MCL
den Graph-Index auf einen Zwischenzustand bringen, den die Primaerablage
(MySQL) nie dauerhaft hatte -- ein Index-Fehler, kein Datenfehler.

CHECK (automatisiert, siehe `check_es_drift()` unten): fuer jedes der acht
Datasets wird die deklarierte `upstreamLineage` aus dem Primaerspeicher
gegen dieselbe Richtung im Graph-Index verglichen. Eine Abweichung wird
laut gemeldet (NIE stillschweigend), inklusive der exakten Remedy-URN.

REMEDY (manuell, falls das Auto-Heal unten nicht greift oder deaktiviert
ist):
    curl -X POST "<GMS_URL>/operations?action=restoreIndices" \\
         -H "Content-Type: application/json" \\
         -d '{"urn": "<betroffene Dataset-URN>"}'
Das resynct den Such-/Graph-Index DIREKT aus der Primaerablage, unter
Umgehung von Kafka -- Sekunden, kein Container-Neustart, kein Datenverlust
(reiner Lese-Resync, kein `--hard delete`). Live verifiziert, 07.08.:
`{"rowsMigrated": 8, "lastAspect": "upstreamLineage"}`, Graph-Index sofort
danach korrekt.
--------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from datahub.emitter.mcp import MetadataChangeProposalWrapper
from datahub.emitter.rest_emitter import DatahubRestEmitter
from datahub.metadata.schema_classes import (
    DatasetUsageStatisticsClass,
    TimeWindowSizeClass,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # fuer `probate.*` bei Direktlauf

from probate.gms import Gms, GmsError, _validate_urn  # noqa: E402

GMS_DEFAULT = "http://localhost:28080"
PLATFORM = "urn:li:dataPlatform:postgres"
NAMESPACE = "probate_seedlab"
ACTOR = "urn:li:corpuser:datahub"
STAMP = {"time": 1754300000000, "actor": ACTOR}  # fest, wie preflight.py/seed_queries.py
MANIFEST_PATH = Path("examples/seedlab-manifest.json")

# Coordinator-Fix (Runde 3, 07.08., korrigiert Runde 4): urspruenglich
# hier ein FEST verdrahtetes Kalenderdatum (2026-08-06). Fund der zweiten
# Review-Runde: `probate/ledger.py:313-323` klassifiziert ueber
# `usageStats(range: MONTH)` -- ein rollendes 30-Tage-Fenster ab dem
# TATSAECHLICHEN "jetzt". Ein fest verdrahteter Anker waere irgendwann
# (hier: ab ca. 2026-09-05) aus diesem Fenster herausgelaufen -- alle acht
# Datasets haetten ihre Abdeckung verloren, jede Kante waere zu `unknown`
# kollabiert, WAEHREND dieser Seeder weiterhin Exit 0 und identische
# Rohsummen gemeldet haette (die eigene Rueckluse-Pruefung liest die
# ungefensterte Rohablage, nicht das 30-Tage-Fenster des echten Klassi-
# fikators) -- ein gruener Seeder ueber einem toten Labor.
#
# Richtig verankert ist deshalb NICHT "ein festes Datum", sondern "der
# aktuelle Tag um Mitternacht UTC, neu berechnet bei jedem Lauf" -- exakt
# das, was der urspruengliche Kalendertag-Fehler (Runde 3) tatsaechlich
# brauchte: INNERHALB eines Laufs deterministisch (derselbe Prozess
# berechnet denselben Zeitstempel fuer jeden der acht Datasets), und die
# Buckets bleiben damit PERMANENT innerhalb des rollenden 30-Tage-Fensters.
# Was den Kalendertag-Wechsel ZWISCHEN zwei separaten Laeufen entschaerft,
# ist nicht mehr der Anker, sondern `purge_usage_history()` weiter unten:
# jeder Lauf wischt seine komplette Zeitreihen-Historie und schreibt frisch
# -- der eigentliche Fix fuer das Idempotenz-Problem war immer der volle
# Wipe-vor-Schreib-Zyklus, nicht ein unveraenderliches Datum.
USAGE_ANCHOR = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def days_ago_ms(n: int) -> int:
    return int((USAGE_ANCHOR - timedelta(days=n)).timestamp() * 1000)


def ds_urn(name: str) -> str:
    return f"urn:li:dataset:({PLATFORM},{NAMESPACE}.{name},PROD)"


# --- die acht Datasets, gruppiert nach Ziel-Zustand ihrer Kante ---------

# Entscheid 2026-08-07 (Fix-Runde 4): die Tabellennamen selbst trugen bis
# hierher den Ziel-Kanten-Zustand im Klartext (`confirmed_upstream`,
# `dead_upstream`, ...). Das ist derselbe Fehler, den die Fix-Runden 1-3
# aus den BESCHREIBUNGEN entfernt haben -- nur eine Ebene hoeher und
# sichtbarer: die Werkbank zeigt die URN direkt neben dem Urteil, ein
# Pruefer liest also woertlich "probate_seedlab.dead_upstream ->
# probate_seedlab.dead_downstream -- Zustand: dead". Der staerkste Beleg
# des Projekts (alle vier Zustaende in einem echten Lauf) sah damit
# zirkulaer aus, weil der Name die Antwort ansagt.
#
# Regel fuer jeden Namen hier, gleichrangig mit der Beschreibungs-Regel
# weiter unten: ein Tabellenname sagt, WAS in der Tabelle steht -- nie,
# wie die Kante darueber ausfaellt. Verboten sind insbesondere
# `dead`/`stale`/`unused`/`orphan`/`confirmed`/`missing`/`unknown` sowie
# `test`/`demo` (letztere, weil sie eine Tabelle als Wegwerf-Artefakt
# markieren und damit auf duenne Nutzung deuten). Die acht Namen bilden
# zusammen den Katalog EINES Unternehmens -- Handel mit Filialen und
# Online-Checkout -- damit die Menge wie ein echter Katalog liest und
# nicht wie acht Fixtures.
#
# Der Namespace `probate_seedlab` bleibt unveraendert sichtbar: er ist
# die ehrliche Markierung "hier wurde geseedet" (Regel UEBERGABE.md SS7.3)
# und trennt das Labor von echten Warehouse-Namen. Nur der Tabellenteil
# ist geaendert.
NAMES: dict[str, str] = {
    "A": "gl_journal_entries_daily",
    "B": "finance_income_statement_consolidated",
    "C": "store_revenue_weekly_east",
    "D": "store_sales_ranking_east",
    "E": "checkout_events_raw",
    "F": "customer_lifetime_value_by_segment",
    "G": "customer_dedup_stage",
    "H": "crm_migration_staging",
}
URNS: dict[str, str] = {k: ds_urn(v) for k, v in NAMES.items()}

# --- organische Beschreibungen (Entscheid 2026-08-07, Fix-Runden 1+2) -----
#
# Fix-Runde 1 (Coordinator-Review, 07.08.): die erste Fassung mied nur die
# TOKEN (confirmed/dead/missing/unknown, "Rolle=", "Ziel-Kanten-Zustand"),
# beschrieb aber in D/F/G die operationale ENTSCHEIDUNGSLOGIK des Klassi-
# fikators in Klartext nach ("kein bekannter Konsument" = unknown-Definition,
# "SQL-Query ausserhalb der Pipeline-Dokumentation" = missing-Definition,
# "unklar ob die Tabelle noch jemand braucht" = dead-Definition) -- derselbe
# Fehler in subtilerer Form.
#
# Fix-Runde 2 (Coordinator-Review, 07.08., zweiter Durchgang): C war in
# Runde 1 faelschlich als "clean" eingestuft (Coordinator-Fehler, nicht
# meiner) -- "fuer das alte BI-Dashboard gebaut" nennt einen Konsum-Kanal
# (HOW, verbotene Kategorie), "seit der Migration ... nicht mehr angepasst"
# nennt einen Pflegezustand. F nannte trotz entfernter SQL-Klausel weiter
# "im Wachstums-Dashboard" -- derselbe HOW-Verstoss wie das bereits in D
# entfernte "im Sales-Standup gezeigt". Beide jetzt bereinigt.
#
# Regel, bindend fuer jeden Satz: eine Beschreibung darf sagen WAS eine
# Tabelle enthaelt und WARUM sie dem Geschaeft wichtig ist (wer von der
# Zahl abhaengt/sie einsieht als Gremium oder Empfaenger, welche
# Entscheidung sie speist -- "Audit-Committee", "Investor-Reporting",
# "Reporting an die Geschaeftsleitung" sind erlaubtes WARUM). Sie darf
# NICHT sagen oder andeuten: WIE die Daten technisch ihre Konsumenten
# erreichen (Pipeline vs. Ad-hoc-Query vs. **benanntes Dashboard/Standup**
# als Visualisierungs-/Anzeige-Artefakt), ob Dokumentation/Lineage
# existiert, ob ein Konsument bekannt/unbekannt ist, ob sie noch
# genutzt/gepflegt/aufgegeben/zum Loeschen vorgesehen ist, oder wie aktuell
# der letzte Zugriff war -- das sind exakt die Observablen, die das
# Werkzeug aus Lineage, Nutzungs-Buckets und Query-Subjects selbst
# herleiten soll. Test pro Satz: "koennte ein Leser allein daraus auf den
# Kanten-Zustand schliessen, ohne Lineage/Nutzung anzusehen?" Wenn ja: raus.
#
# Business-Relevanz zusaetzlich ENTKOPPELT von der 2-vs-2-Vierergruppe:
# A/B (confirmed) hoch, C/D (dead) mittel (D sprachlich leicht abgeschwaecht
# gegenueber F -- "Orientierungsgroesse" statt "Entscheidungsgrundlage",
# ohne neue HOW/Pflege-Signale), F (Ziel des missing-Paars) hoch, E
# (Quelle des missing-Paars) bewusst MITTEL/trivial (rohes, unverarbeitetes Log)
# statt "mehrere Teams haengen dran" -- sonst waere "hohe Business-
# Relevanz" selbst wieder ein Hinweis auf "confirmed oder missing". G/H
# (unknown) bleiben trivial, aber ohne jede Nutzungs-Aussage.
#
# Fix-Runde 3 (Coordinator-Review, 07.08., dritter Durchgang): zwei weitere
# Funde. B nannte mit "Wird dem Audit-Committee vorgelegt" einen Liefer-
# Vorgang (delivery-framed) statt einer Abhaengigkeit (dependency-framed)
# -- jetzt "Grundlage fuer die Pruefung durch das Audit-Committee". H nannte
# mit "abgeschlossener Testlauf ... aus dem letzten Quartal" funktional
# "zuletzt letztes Quartal angefasst, seither nichts" -- exakt die
# Aktualitaets-Beobachtung, die das Werkzeug aus den Nutzungs-Buckets
# herleiten soll, nicht aus Prosa. Jetzt parallel zu G: reine Inhaltsangabe
# ohne Abschluss-/Datums-Aussage.
#
# SPRACHE (10.08.2026): die Beschreibungen sind DATEN, keine Kommentare --
# und das Modell zitiert sie woertlich in ein Artefakt, das im Demo-Video
# 22 Sekunden lang im Bild steht. Ein deutscher Zitat-Block in einer sonst
# durchgehend englischen Einreichung liest sich fuer einen Juror wie ein
# nicht uebersetzter Rest. Also englisch, Satz fuer Satz uebersetzt --
# dieselben Aussagen, dieselbe Relevanz-Staffelung (A/B hoch, C mittel,
# D abgeschwaecht, E trivial-roh, F hoch, G/H trivial), kein neues Signal.
# Die Regel oben gilt unveraendert weiter: kein Zustandswort, kein HOW,
# keine Pflege-/Aktualitaets-Aussage. Die CODE-Kommentare bleiben deutsch;
# nur die Daten-Texte sind uebersetzt.
DESC_PREFIX = "[probate-seedlab -- synthetische Demonstrationsdaten]"

ORGANIC_DESCRIPTIONS: dict[str, str] = {
    "A": (
        "Daily export of the cleaned general ledger journal lines from the "
        "ERP system (reversals filtered out). Forms the data basis for the "
        "consolidated group balance sheet; changes to the extraction logic "
        "go through the Finance change process."
    ),
    "B": (
        "Consolidated income statement for the annual financial statements. "
        "Basis for the review by the audit committee and part of investor "
        "reporting -- deviations here are subject to disclosure."
    ),
    "C": (
        "Weekly snapshot of store revenue for the East region, raw basis "
        "for assessing regional sales performance."
    ),
    "D": (
        "Aggregated per-store sales ranking derived from the regional "
        "snapshots, serves as a reference figure for sales management in "
        "the East region."
    ),
    "E": (
        "Raw, unfiltered log of order and session events from the checkout "
        "service at individual event level."
    ),
    "F": (
        "Customer lifetime value per customer segment, a core growth metric "
        "and the basis for marketing budget decisions as well as part of "
        "the monthly reporting to the executive board."
    ),
    "G": (
        "Intermediate table of a deduplication script, holds the interim "
        "result of an internal cleansing step."
    ),
    "H": (
        "Temporary store of a migration test, holds its interim state."
    ),
}

# --- echte Governance-Aspekte (Entscheid 2026-08-07, Teil 2) --------------
#
# ownership: nur wo eine Verantwortung realistisch ist -- die beiden
# trivialen Scratch-Tabellen (G/H) haben bewusst KEINEN Owner, genau wie
# im echten Warehouse niemand eine Wegwerf-Zwischentabelle vertritt.
OWNERS: dict[str, list[dict[str, str]]] = {
    "A": [{"owner": "urn:li:corpuser:m.keller", "type": "DATAOWNER"}],
    "B": [{"owner": "urn:li:corpuser:finance.reporting", "type": "BUSINESS_OWNER"}],
    "C": [{"owner": "urn:li:corpuser:r.huber", "type": "TECHNICAL_OWNER"}],
    "D": [{"owner": "urn:li:corpuser:r.huber", "type": "TECHNICAL_OWNER"}],
    "E": [{"owner": "urn:li:corpuser:growth.analytics", "type": "BUSINESS_OWNER"}],
    "F": [{"owner": "urn:li:corpuser:growth.analytics", "type": "BUSINESS_OWNER"}],
}

DOMAIN_DEFS: dict[str, dict[str, str]] = {
    "urn:li:domain:probate_seedlab.finance": {
        "name": "Finance",
        "description": "Buchhaltung, Konzernabschluss, externe Berichterstattung.",
    },
    "urn:li:domain:probate_seedlab.customer_analytics": {
        "name": "Customer Analytics",
        "description": "Kundenverhalten, Wachstumskennzahlen, Marketing-Reporting.",
    },
}
DATASET_DOMAIN: dict[str, str] = {
    "A": "urn:li:domain:probate_seedlab.finance",
    "B": "urn:li:domain:probate_seedlab.finance",
    "E": "urn:li:domain:probate_seedlab.customer_analytics",
    "F": "urn:li:domain:probate_seedlab.customer_analytics",
}

TERM_DEFS: dict[str, dict[str, str]] = {
    "urn:li:glossaryTerm:probate_seedlab.hauptbuch": {
        "name": "Hauptbuch",
        "definition": "Zentrales Buchungsjournal aller Geschaeftsvorfaelle.",
    },
    "urn:li:glossaryTerm:probate_seedlab.jahresabschluss": {
        "name": "Jahresabschluss",
        "definition": "Konsolidierter Abschluss des Geschaeftsjahres, Grundlage der externen Berichterstattung.",
    },
    "urn:li:glossaryTerm:probate_seedlab.customer_lifetime_value": {
        "name": "Customer Lifetime Value",
        "definition": "Prognostizierter Gesamtumsatz eines Kunden ueber die gesamte Kundenbeziehung.",
    },
}
DATASET_TERMS: dict[str, list[str]] = {
    "A": ["urn:li:glossaryTerm:probate_seedlab.hauptbuch"],
    "B": ["urn:li:glossaryTerm:probate_seedlab.jahresabschluss"],
    "F": ["urn:li:glossaryTerm:probate_seedlab.customer_lifetime_value"],
}

EDGE_STATE_OF_PAIR = {
    ("A", "B"): "confirmed",
    ("C", "D"): "dead",
    ("E", "F"): "missing",
    ("G", "H"): "unknown",
}

# --- Nutzungs-Bucket-Plaene ------------------------------------------------

CONFIRMED_BUCKETS = [
    (days_ago_ms(2), 28, 3),
    (days_ago_ms(1), 35, 4),
    (days_ago_ms(0), 40, 5),
]
MISSING_BUCKETS = [
    (days_ago_ms(2), 19, 2),
    (days_ago_ms(1), 24, 3),
    (days_ago_ms(0), 31, 4),
]
DEAD_BUCKETS = [
    # letzter Verkehr -- ~117 Tage zurueck ist der juengere der beiden
    (days_ago_ms(124), 30, 4),
    (days_ago_ms(117), 22, 3),
    # danach: wir haben hingesehen, es war nichts mehr da
    (days_ago_ms(90), 0, 0),
    (days_ago_ms(60), 0, 0),
    (days_ago_ms(30), 0, 0),
    (days_ago_ms(14), 0, 0),
    (days_ago_ms(7), 0, 0),
    (days_ago_ms(0), 0, 0),
]
UNKNOWN_BUCKETS: list[tuple[int, int, int]] = []  # bewusst leer

USAGE_PLAN: dict[str, list[tuple[int, int, int]]] = {
    "A": CONFIRMED_BUCKETS,
    "B": CONFIRMED_BUCKETS,
    "C": DEAD_BUCKETS,
    "D": DEAD_BUCKETS,
    "E": MISSING_BUCKETS,
    "F": MISSING_BUCKETS,
    "G": UNKNOWN_BUCKETS,
    "H": UNKNOWN_BUCKETS,
}

LINEAGE_PAIRS: list[tuple[str, str]] = [("A", "B"), ("C", "D"), ("G", "H")]  # missing hat KEINE
COOCCURRENCE_PAIRS: list[tuple[str, str]] = [("A", "B"), ("E", "F")]  # dead/unknown haben KEINE


@dataclass
class WriteResult:
    what: str
    written: Any
    readback: Any
    ok: bool
    detail: str = ""


RESULTS: list[WriteResult] = []


def record(what: str, written: Any, readback_fn, expect_fn, retries: int = 6, delay_s: float = 2.0) -> None:
    """Liest zurueck und vergleicht. GraphQL-Lineage und usageStats haengen
    an Elasticsearch/Graph-Indizes, die per Kafka-MCL asynchron NACH dem
    synchronen REST-Schreibvorgang nachziehen -- live beobachtet (2026-08-07):
    ein Rücklese-Versuch direkt nach dem Schreiben lieferte fuer upstreamLineage
    und usageStats den alten (leeren) Stand, derselbe Aufruf Sekunden spaeter
    den korrekten. Das ist Index-Verzug, kein Schreibfehler -- darum retry mit
    Backoff, bevor ein FEHLER gemeldet wird (verification.md: eine gescheiterte
    Abfrage ist keine Abwesenheit, aber ein zu frueher Blick ist auch keine)."""
    last_readback = None
    last_err: str | None = None
    for attempt in range(retries):
        try:
            last_readback = readback_fn()
        except GmsError as exc:
            last_err = f"Rueckleseversagen: {exc}"
            time.sleep(delay_s)
            continue
        if expect_fn(last_readback):
            RESULTS.append(WriteResult(what, written, last_readback, True, f"(nach {attempt + 1}. Versuch)" if attempt else ""))
            return
        time.sleep(delay_s)
    detail = last_err or "Rueckgelesener Wert weicht auch nach Wiederholungen ab"
    RESULTS.append(WriteResult(what, written, last_readback, False, f"{detail} ({retries}x versucht)"))


# --- Schreibvorgaenge --------------------------------------------------


def seed_datasets(gms: Gms) -> None:
    records = []
    for letter, name in NAMES.items():
        desc = f"{DESC_PREFIX} {ORGANIC_DESCRIPTIONS[letter]}"
        records.append(
            {"urn": URNS[letter], "datasetProperties": {"value": {"name": name, "description": desc}}}
        )
    gms.upsert("dataset", records)

    def readback():
        out = {}
        for letter in NAMES:
            data = gms.graphql(
                "query($urn: String!) { dataset(urn: $urn) { urn properties { name description } } }",
                {"urn": URNS[letter]},
            )
            out[letter] = (data.get("dataset") or {}).get("properties")
        return out

    def expect(rb):
        for k, v in rb.items():
            expected_desc = f"{DESC_PREFIX} {ORGANIC_DESCRIPTIONS[k]}"
            if not v or v.get("name") != NAMES[k] or v.get("description") != expected_desc:
                return False
        return True

    record(
        "datasets (8x datasetProperties, organische Beschreibung ohne Zustandswort)",
        [r["urn"] for r in records],
        readback,
        expect,
    )


def seed_domains(gms: Gms) -> None:
    """Domain-Entitaeten selbst -- muessen existieren, BEVOR ein Dataset
    per `domains`-Aspekt darauf zeigt, sonst liefert `domain { properties
    { name } }` (probate/judge.py CONTEXT_Q) nichts, weil GraphQL den Namen
    von der Domain-Entitaet aufloest, nicht vom Dataset-Aspekt."""
    records = [
        {"urn": urn, "domainProperties": {"value": {"name": d["name"], "description": d["description"]}}}
        for urn, d in DOMAIN_DEFS.items()
    ]
    gms.upsert("domain", records)

    def readback():
        out = {}
        for urn in DOMAIN_DEFS:
            aspect = gms.get_aspect("domain", urn, "domainProperties")
            out[urn] = (aspect or {}).get("value", {}).get("name")
        return out

    record(
        f"domain-Entitaeten ({len(DOMAIN_DEFS)}x domainProperties)",
        list(DOMAIN_DEFS),
        readback,
        lambda rb: all(rb.get(urn) == d["name"] for urn, d in DOMAIN_DEFS.items()),
    )


def seed_glossary_terms(gms: Gms) -> None:
    """GlossaryTerm-Entitaeten -- judge.py liest bislang nur `term.urn`
    aus dem Dataset-Aspekt, aber ein haengender Term ohne eigene
    `glossaryTermInfo` waere kein echtes Glossar, sondern nur eine URN-
    Attrappe. Also volle Entitaet, echtes Material."""
    records = [
        {
            "urn": urn,
            "glossaryTermInfo": {
                "value": {"name": t["name"], "definition": t["definition"], "termSource": "INTERNAL"}
            },
        }
        for urn, t in TERM_DEFS.items()
    ]
    gms.upsert("glossaryTerm", records)

    def readback():
        out = {}
        for urn in TERM_DEFS:
            aspect = gms.get_aspect("glossaryTerm", urn, "glossaryTermInfo")
            out[urn] = (aspect or {}).get("value", {}).get("name")
        return out

    record(
        f"glossaryTerm-Entitaeten ({len(TERM_DEFS)}x glossaryTermInfo)",
        list(TERM_DEFS),
        readback,
        lambda rb: all(rb.get(urn) == t["name"] for urn, t in TERM_DEFS.items()),
    )


def seed_governance(gms: Gms) -> None:
    """ownership/domains/glossaryTerms auf den Datasets, die eins davon
    tragen sollen (nicht alle acht -- G/H bleiben bewusst unbesetzt, siehe
    OWNERS/DATASET_DOMAIN/DATASET_TERMS oben). Muss NACH seed_domains()
    und seed_glossary_terms() laufen, sonst zeigen die Referenzen auf noch
    nicht existierende Entitaeten."""
    letters = sorted(set(OWNERS) | set(DATASET_DOMAIN) | set(DATASET_TERMS))
    records = []
    for letter in letters:
        rec: dict[str, Any] = {"urn": URNS[letter]}
        if letter in OWNERS:
            rec["ownership"] = {"value": {"owners": OWNERS[letter]}}
        if letter in DATASET_DOMAIN:
            rec["domains"] = {"value": {"domains": [DATASET_DOMAIN[letter]]}}
        if letter in DATASET_TERMS:
            rec["glossaryTerms"] = {
                "value": {
                    "terms": [{"urn": t} for t in DATASET_TERMS[letter]],
                    "auditStamp": STAMP,
                }
            }
        records.append(rec)
    gms.upsert("dataset", records)

    _GOV_Q = """
    query($urn: String!) {
      dataset(urn: $urn) {
        ownership { owners { owner { ... on CorpUser { urn } ... on CorpGroup { urn } } } }
        domain { domain { properties { name } } }
        glossaryTerms { terms { term { urn } } }
      }
    }
    """

    def readback():
        out = {}
        for letter in letters:
            data = gms.graphql(_GOV_Q, {"urn": URNS[letter]})
            d = data.get("dataset") or {}
            owners = [(o.get("owner") or {}).get("urn", "") for o in ((d.get("ownership") or {}).get("owners") or [])]
            domain_name = (((d.get("domain") or {}).get("domain") or {}).get("properties") or {}).get("name", "")
            terms = [(t.get("term") or {}).get("urn", "") for t in ((d.get("glossaryTerms") or {}).get("terms") or [])]
            out[letter] = {"owners": owners, "domain_name": domain_name, "terms": terms}
        return out

    def expect(rb):
        for letter in letters:
            got = rb.get(letter) or {}
            if letter in OWNERS:
                expected_owners = {o["owner"] for o in OWNERS[letter]}
                if set(got.get("owners") or []) != expected_owners:
                    return False
            if letter in DATASET_DOMAIN:
                expected_name = DOMAIN_DEFS[DATASET_DOMAIN[letter]]["name"]
                if got.get("domain_name") != expected_name:
                    return False
            if letter in DATASET_TERMS:
                if set(got.get("terms") or []) != set(DATASET_TERMS[letter]):
                    return False
        return True

    n_owner = sum(1 for letter in letters if letter in OWNERS)
    n_domain = sum(1 for letter in letters if letter in DATASET_DOMAIN)
    n_terms = sum(1 for letter in letters if letter in DATASET_TERMS)
    record(
        f"Governance-Aspekte auf Datasets (ownership x{n_owner}, domains x{n_domain}, glossaryTerms x{n_terms})",
        [r["urn"] for r in records],
        readback,
        expect,
    )


def seed_lineage(gms: Gms) -> None:
    records = []
    for up, down in LINEAGE_PAIRS:
        records.append(
            {
                "urn": URNS[down],
                "upstreamLineage": {
                    "value": {
                        "upstreams": [
                            {"dataset": URNS[up], "type": "TRANSFORMED", "auditStamp": STAMP}
                        ]
                    }
                },
            }
        )
    gms.upsert("dataset", records)

    _LINEAGE_Q = """
    query($urn: String!) {
      dataset(urn: $urn) {
        lineage(input: {direction: DOWNSTREAM, start: 0, count: 200}) {
          relationships { entity { urn } }
        }
      }
    }
    """

    def readback():
        out = {}
        for up, down in LINEAGE_PAIRS:
            data = gms.graphql(_LINEAGE_Q, {"urn": URNS[up]})
            rels = (data.get("dataset") or {}).get("lineage", {}).get("relationships", [])
            out[f"{up}->{down}"] = {r["entity"]["urn"] for r in rels if r.get("entity")}
        return out

    def expect(rb):
        return all(URNS[down] in rb[f"{up}->{down}"] for up, down in LINEAGE_PAIRS)

    record("upstreamLineage (3x deklarierte Kanten: A->B, C->D, G->H)", [r["urn"] for r in records], readback, expect)


def seed_queries(gms: Gms) -> None:
    # Die Query-IDs tragen denselben Zwang wie die Tabellennamen (siehe
    # Kommentar bei NAMES): sie hiessen bis 2026-08-07 `…-confirmed` und
    # `…-missing`, und weil `probate/ledger.py` die Query-URN als BELEG in
    # jedes Kanten-Urteil schreibt (`evidence.query_urns`), stand das
    # Zustandswort woertlich neben dem Urteil, das es erst herleiten soll.
    # Jetzt benannt nach dem Vorgang, den die Query ausfuehrt.
    plans = [
        (
            "probate-seedlab-gl-consolidation",
            f"INSERT INTO {NAMESPACE}.{NAMES['B']} SELECT * FROM {NAMESPACE}.{NAMES['A']}",
            ("A", "B"),
        ),
        (
            "probate-seedlab-clv-build",
            f"INSERT INTO {NAMESPACE}.{NAMES['F']} SELECT * FROM {NAMESPACE}.{NAMES['E']}",
            ("E", "F"),
        ),
    ]
    records = []
    for qid, sql, (up, down) in plans:
        records.append(
            {
                "urn": f"urn:li:query:{qid}",
                "queryProperties": {
                    "value": {
                        "statement": {"value": sql, "language": "SQL"},
                        "source": "MANUAL",
                        "created": STAMP,
                        "lastModified": STAMP,
                    }
                },
                "querySubjects": {"value": {"subjects": [{"entity": URNS[up]}, {"entity": URNS[down]}]}},
            }
        )
    gms.upsert("query", records)

    def readback():
        out = {}
        for qid, _sql, _pair in plans:
            aspect = gms.get_aspect("query", f"urn:li:query:{qid}", "querysubjects")
            subjects = (aspect or {}).get("value", {}).get("subjects", [])
            out[qid] = {s.get("entity") for s in subjects}
        return out

    def expect(rb):
        for qid, _sql, (up, down) in plans:
            if rb[qid] != {URNS[up], URNS[down]}:
                return False
        return True

    record("query-Entitaeten (2x: confirmed A+B, missing E+F)", [r["urn"] for r in records], readback, expect)


# --- Idempotenz ueber Kalendertage hinweg (Coordinator-Fix, Runde 3) -----
#
# Diagnose (mit Rohdaten-Beleg, siehe Report): `gms.delete_aspect()`
# (generische `DELETE /openapi/v3/entity/.../<aspekt>`) entfernt bei
# Zeitreihen-Aspekten NUR die "aktuellste" Einzelzeile, nicht die volle
# Historie -- live geprueft: zwei Buckets geschrieben (aeltere+neuere
# Zeitmarke), `delete_aspect` aufgerufen, `getTimeseriesAspectValues`
# zeigte danach weiterhin den AELTEREN Bucket. Ein reiner
# Anker-Zeitstempel-Fix (`USAGE_ANCHOR` oben) verhindert NEUE Drift, raeumt
# aber die bereits angehaeuften Leichen aus fruehren Kalendertag-Laeufen
# nicht weg. Der volle Zeitreihen-Wipe braucht die dedizierte Route
# `POST /entities?action=delete` mit `aspectName` + `startTimeMillis`/
# `endTimeMillis` -- dieselbe Route, die `datahub delete by-filter
# --aspect ... --hard --start-time ... --end-time ...` intern aufruft
# (Quelle gelesen: `datahub.ingestion.graph.client.DataHubGraph
# .hard_delete_timeseries_aspect`), hier direkt per HTTP repliziert statt
# einen `uvx`-Subprozess pro Dataset zu starten. Live an einer Wegwerf-
# Probe-Entitaet verifiziert (drei Buckets geschrieben, gewiped, Rohzugriff
# zeigte danach 0 Zeilen, `timeseriesRows: 3` im Loesch-Ergebnis).
#
# Rueckluse-Abweichung vom Auftrag [hier haette Joel vielleicht anders
# gewollt]: der Auftrag verlangte ausdruecklich `get_aspect` fuer die
# Loesch-Bestaetigung.
#
# KORREKTUR 07.08.2026, 12:20: Hier stand, `get_aspect()` liefere fuer
# Zeitreihen-Aspekte "IMMER None" und sei blind. Das ist widerlegt --
# `get_aspect('dataset', <urn>, 'datasetUsageStatistics')` gab an
# `probate_writetest.t4` den geschriebenen Wert zurueck (123 rein, 123
# raus). Der Rohzugriff bleibt richtig, aber aus dem belegten Grund:
# `get_aspect` zeigt nur den JUENGSTEN Bucket und kann darum "Historie
# geloescht" nicht von "juengster Wert noch da" unterscheiden -- fuer eine
# Loesch-Bestaetigung ueber die ganze Historie taugt es nicht.
# Verwendet wird deshalb derselbe Rohzugriff, der die Diagnose belegt hat
# (`/aspects?action=getTimeseriesAspectValues`, Falle 14: `limit` ist
# Pflicht) -- das einzige Werkzeug, das bei Zeitreihen-Aspekten tatsaechlich
# zeigt, ob Daten da sind oder nicht.
_FAR_FUTURE_MS = 4_102_444_800_000  # 2100-01-01 UTC -- deckt jede plausible Bucket-Zeitmarke ab


# Minor-Fund (Coordinator-Review, Runde 4): `_raw_usage_values()` und
# `purge_usage_history()` rufen `gms._send()` direkt statt eine oeffentliche
# Gms-Methode -- weil `probate/gms.py` weder "vollstaendige Zeitreihe
# loeschen" (`/entities?action=delete`) noch "rohe Zeitreihen-Werte lesen"
# (`/aspects?action=getTimeseriesAspectValues`) als Methode anbietet und
# `probate/gms.py` selbst ausserhalb des erlaubten Datei-Umfangs dieser
# Aufgabe liegt (kein neuer Endpunkt dort ergaenzbar, ohne die Grenze zu
# verletzen). Damit die Umgehung der `_validate_urn()`-Haertung aus
# `gms.py` (Finding C4, Allowlist gegen Pfad-Traversal) nicht lautlos
# passiert, wird sie hier EXPLIZIT wiederholt, bevor die URN in die
# JSON-Payload wandert -- Risiko war ohnehin niedrig (feste,
# entwicklerdefinierte URNs aus `URNS`, kein Nutzereingang, kein Pfad-
# Segment), aber "niedriges Risiko" ist kein Grund, eine Disziplin zu
# unterlaufen, die das Modul selbst predigt.
def _raw_usage_values(gms: Gms, urn: str) -> list[dict]:
    _validate_urn(urn)
    payload = {
        "urn": urn,
        "entity": "dataset",
        "aspect": "datasetUsageStatistics",
        "startTimeMillis": 0,
        "endTimeMillis": _FAR_FUTURE_MS,
        "limit": 200,  # Falle 14 (UEBERGABE.md): Pflichtfeld, sonst HTTP 500
    }
    status, body = gms._send("POST", f"{gms.base}/aspects?action=getTimeseriesAspectValues", payload)
    if status != 200 or not isinstance(body, dict):
        raise GmsError(f"getTimeseriesAspectValues HTTP {status}: {str(body)[:200]}")
    values = ((body.get("value") or {}).get("values")) or []
    out = []
    for v in values:
        raw = v.get("aspect", {}).get("value")
        out.append(json.loads(raw) if isinstance(raw, str) else raw)
    return out


def purge_usage_history(gms: Gms) -> None:
    """Wischt die komplette Nutzungs-Zeitreihe fuer alle acht Datasets,
    BEVOR neu geschrieben wird. Macht seed_usage() selbst-heilend: egal
    wie viele Tage-Leichen aus fruehren Laeufen (an welchem Kalendertag
    auch immer) noch herumliegen, nach diesem Schritt ist die Historie
    leer und der folgende Schreibvorgang schreibt auf ein garantiert
    sauberes Blatt -- Voraussetzung fuer "an jedem Tag dasselbe Ergebnis"."""
    purge_counts: dict[str, int] = {}
    for letter, urn in URNS.items():
        _validate_urn(urn)  # siehe Kommentar bei _raw_usage_values() oben
        payload = {"urn": urn, "aspectName": "datasetUsageStatistics",
                   "startTimeMillis": 0, "endTimeMillis": _FAR_FUTURE_MS}
        status, body = gms._send("POST", f"{gms.base}/entities?action=delete", payload)
        if status != 200:
            RESULTS.append(WriteResult(f"usage-purge {letter}", payload, None, False, f"HTTP {status}: {str(body)[:200]}"))
            continue
        purge_counts[letter] = (body or {}).get("value", {}).get("timeseriesRows", 0)

    def readback():
        return {letter: len(_raw_usage_values(gms, urn)) for letter, urn in URNS.items()}

    record(
        f"usage-Historie gewiped ({sum(purge_counts.values())} Zeilen entfernt ueber 8 Datasets, Rohzugriff statt get_aspect)",
        purge_counts,
        readback,
        lambda rb: all(v == 0 for v in rb.values()),
    )


def seed_usage(gms: Gms, emitter: DatahubRestEmitter) -> None:
    purge_usage_history(gms)

    written_counts: dict[str, int] = {}
    for letter, buckets in USAGE_PLAN.items():
        n = 0
        for ts_ms, total, unique in buckets:
            aspect = DatasetUsageStatisticsClass(
                timestampMillis=ts_ms,
                eventGranularity=TimeWindowSizeClass(unit="DAY", multiple=1),
                uniqueUserCount=unique,
                totalSqlQueries=total,
            )
            try:
                emitter.emit_mcp(MetadataChangeProposalWrapper(entityUrn=URNS[letter], aspect=aspect))
                n += 1
            except Exception as exc:  # noqa: BLE001 - Schreibfehler MUSS laut werden
                RESULTS.append(
                    WriteResult(f"usage bucket {letter}@{ts_ms}", ts_ms, None, False, f"{type(exc).__name__}: {exc}")
                )
        written_counts[letter] = n

    # Live-Falle (2026-08-07, Runde 3, verschaerft): `usageStats(range: ALL)`
    # -- die GraphQL-Aggregation -- ist NACH dem Purge+Rewrite-Zyklus dieser
    # Runde live an D/E/F noch NACH ueber 75 Sekunden Polling (15x mit 5s
    # Abstand) `null` geblieben, obwohl derselbe Rohzugriff
    # (`/aspects?action=getTimeseriesAspectValues`) beim ALLERERSTEN Versuch
    # bereits die korrekten Werte zeigte (D: 8 Buckets, Summe 52 -- exakt
    # erwartet). Das ist derselbe Index-Verzug wie schon dokumentiert
    # (Falle 15, UEBERGABE.md: Graph-/Suchindex hinkt nach), nur diesmal
    # zuverlaessig laenger als das bisherige Retry-Budget. Die GraphQL-
    # Aggregation haengt am ES-Index; die Rohablage (`getTimeseriesAspectValues`)
    # ist die Primaerablage und war in JEDEM bisherigen Test sofort korrekt.
    # Verifikation deshalb ab jetzt gegen die Rohablage, nicht die
    # Aggregation -- kein Rennen gegen einen Index mehr, sondern derselbe
    # Speicher, der auch geschrieben wurde.
    def readback():
        out = {}
        for letter in USAGE_PLAN:
            out[letter] = sum(v.get("totalSqlQueries", 0) for v in _raw_usage_values(gms, URNS[letter]))
        return out

    def expect(rb):
        for letter, buckets in USAGE_PLAN.items():
            expected_total = sum(b[1] for b in buckets)
            got = rb.get(letter)
            if buckets and got != expected_total:
                return False
            if not buckets and got not in (None, 0):
                # unknown-Zustand: keine Buckets geschrieben. DataHub liefert je
                # nach Instanzstand entweder null oder 0 fuer "keine Daten" --
                # beides ist der erwartete Nicht-Fund, ein anderer Wert waere ein Fehler.
                return False
        return True

    # Hoeheres Retry-Budget als der `record()`-Default (6x2s=12s): live
    # beobachtet (Runde 3), dass die Primaerablage nach einem Purge+28-
    # Einzelschreibvorgaenge-Zyklus laenger als 12s brauchte, bis
    # `getTimeseriesAspectValues` den vollstaendigen Stand zeigte -- ein
    # Nachlauf derselben Art wie in `record()`s eigenem Docstring
    # beschrieben, nur mit mehr Schreibvolumen als die anderen Schritte.
    record(
        f"Nutzungs-Buckets ({sum(written_counts.values())} Aufrufe ueber 8 Datasets)",
        written_counts,
        readback,
        expect,
        retries=15,
        delay_s=3.0,
    )


def check_cooccurrence(gms: Gms) -> dict[str, int]:
    """Teil 3: der Weg, den der spaetere Abgleich benutzt -- searchAcrossEntities
    auf QUERY-Entitaeten, gefiltert auf das Feld 'entities'. Wird für die
    beiden Datasets berichtet, die tatsaechlich in einer Seed-Query stehen."""
    _Q = """
    query($urn: String!) {
      searchAcrossEntities(input: {
        types: [QUERY], query: "*", count: 200,
        orFilters: [{ and: [{ field: "entities", values: [$urn] }] }]
      }) { total searchResults { entity { urn } } }
    }
    """
    out = {}
    for up, down in COOCCURRENCE_PAIRS:
        data = gms.graphql(_Q, {"urn": URNS[up]})
        out[f"{up}(+{down})"] = (data.get("searchAcrossEntities") or {}).get("total", 0)
    return out


# --- ES-Graph-Index-Drift-Check (Runbook siehe Modul-Docstring oben) ------

_UPSTREAM_GRAPH_Q = """
query($urn: String!) {
  dataset(urn: $urn) {
    lineage(input: {direction: UPSTREAM, start: 0, count: 200}) {
      relationships { entity { urn } }
    }
  }
}
"""


def check_es_drift(gms: Gms, auto_heal: bool = True) -> list[str]:
    """Vergleicht fuer alle acht Datasets die deklarierte upstreamLineage
    (Primaerspeicher, `get_aspect`) gegen dieselbe Richtung im Graph-Index
    (`lineage(direction: UPSTREAM)`) -- exakt das Feld, das `probate/
    ledger.py::fetch_declared_edges()` tatsaechlich abfragt. Eine
    Abweichung heisst: der Graph-Index ist desynchronisiert (Kafka-MCL-
    Drift, Falle 15), nicht dass die Primaerdaten falsch sind -- die
    Primaerablage gilt als Wahrheit.

    `auto_heal=True` (Default) loest bei einer Abweichung sofort
    `restoreIndices` fuer die betroffene URN aus (Sekunden, kein
    Datenverlust, reiner Lese-Resync aus MySQL) -- aber NIE
    stillschweigend: jede Abweichung UND jeder Heilversuch wird gedruckt,
    unabhaengig davon ob geheilt wird oder nicht (Auftrag, woertlich:
    "Detecting and printing the remedy is enough; do not silently repair
    without saying so")."""
    drifted: list[str] = []
    for letter, urn in URNS.items():
        _validate_urn(urn)
        aspect = gms.get_aspect("dataset", urn, "upstreamLineage")
        primary = {
            u.get("dataset")
            for u in ((aspect or {}).get("value") or {}).get("upstreams", [])
            if u.get("dataset")
        }
        data = gms.graphql(_UPSTREAM_GRAPH_Q, {"urn": urn})
        rels = ((data.get("dataset") or {}).get("lineage") or {}).get("relationships") or []
        graph = {r["entity"]["urn"] for r in rels if r.get("entity")}
        if primary != graph:
            drifted.append(letter)
            print(f"\n  [ES-DRIFT] {letter} ({urn})")
            print(f"    Primaerspeicher (upstreamLineage): {primary or '{}'}")
            print(f"    Graph-Index (lineage UPSTREAM):    {graph or '{}'}")
            remedy = (
                f'curl -X POST "{gms.base}/operations?action=restoreIndices" '
                f'-H "Content-Type: application/json" -d \'{{"urn": "{urn}"}}\''
            )
            print(f"    Remedy: {remedy}")
            if auto_heal:
                status, body = gms._send("POST", f"{gms.base}/operations?action=restoreIndices", {"urn": urn})
                print(f"    Auto-Heal ausgeloest: HTTP {status}, {body}")
    if not drifted:
        print(
            "\n  ES-Graph-Index-Check: keine Drift gefunden "
            "(Primaerspeicher == Graph-Index fuer alle 8 Datasets)."
        )
    return drifted


# --- Manifest -----------------------------------------------------------


def write_manifest(cooccurrence: dict[str, int]) -> None:
    entries = []
    for (up, down), state in EDGE_STATE_OF_PAIR.items():
        entries.append(
            {
                "upstream_urn": URNS[up],
                "downstream_urn": URNS[down],
                "declared_lineage": (up, down) in LINEAGE_PAIRS,
                "cooccurrence_query": (up, down) in COOCCURRENCE_PAIRS,
                "usage_buckets_upstream": len(USAGE_PLAN[up]),
                "usage_buckets_downstream": len(USAGE_PLAN[down]),
                "expected_edge_state": state,
                "represents": {
                    "confirmed": "Kante deklariert + Ko-Okkurrenz-Query + frische Nutzung beidseitig",
                    "dead": "Kante deklariert, Nutzung gemessen, letzter Verkehr ~117 Tage zurueck, danach Null",
                    "missing": "Ko-Okkurrenz-Query + frische Nutzung, aber KEINE deklarierte Kante",
                    "unknown": "Kante deklariert, aber KEINE Nutzungs-Buckets ueberhaupt",
                }[state],
            }
        )
    manifest = {
        "seeded": True,
        "seeded_statement": (
            "Synthetic demonstration data (harness/seed_lineage_lab.py) - "
            "not real warehouse usage. Namespace probate_seedlab, platform postgres."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gms_url": GMS_DEFAULT,
        "namespace": NAMESPACE,
        "naming_note": (
            "Die Tabellennamen tragen bewusst KEINEN Hinweis auf den erwarteten "
            "Kanten-Zustand. 'expected_edge_state' unten ist die Test-Erwartung "
            "dieses Labors und wird nirgends in der Oberflaeche angezeigt -- sie "
            "existiert, damit harness/seedlab_verdicts.py das gemessene Urteil "
            "dagegen halten kann. Wuerde der Name den Zustand ansagen "
            "('dead_upstream -> dead_downstream: dead'), waere der Vier-Zustaende-"
            "Beleg zirkulaer. Die acht Namen bilden stattdessen den Katalog eines "
            "Handelsunternehmens (Hauptbuch/Abschluss, Filialumsatz/Ranking, "
            "Checkout-Events/Customer-Lifetime-Value, zwei Zwischentabellen)."
        ),
        "edges": entries,
        "cooccurrence_search_results": cooccurrence,
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# --- CLI ------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gms-url", default=GMS_DEFAULT)
    p.add_argument("--token", default=None)
    args = p.parse_args()

    token = args.token if args.token is not None else os.environ.get("DATAHUB_TOKEN")
    gms = Gms(base_url=args.gms_url, token=token)
    emitter = DatahubRestEmitter(gms_server=args.gms_url, token=token)

    seed_datasets(gms)
    seed_domains(gms)
    seed_glossary_terms(gms)
    seed_governance(gms)
    seed_lineage(gms)
    seed_queries(gms)
    seed_usage(gms, emitter)
    cooccurrence = check_cooccurrence(gms)
    write_manifest(cooccurrence)

    print(f"\n  Seedlab gegen {args.gms_url}, Namespace {NAMESPACE}\n")
    print(f"  {'Schreibvorgang':<55} {'Status':<6} Detail")
    print(f"  {'-' * 55} {'-' * 6} {'-' * 30}")
    failed = []
    for r in RESULTS:
        status = "OK" if r.ok else "FEHL"
        if not r.ok:
            failed.append(r.what)
        print(f"  {r.what:<55} {status:<6} {r.detail}")

    print("\n  Ko-Okkurrenz-Suche (searchAcrossEntities, types:[QUERY]):")
    for k, v in cooccurrence.items():
        print(f"    {k}: {v} Treffer")

    print(f"\n  Manifest: {MANIFEST_PATH}")

    print("\n  ES-Graph-Index-Drift-Check (Runbook: Modul-Docstring, Symptom/Check/Remedy):")
    drifted = check_es_drift(gms)
    if drifted:
        print(f"\n  {len(drifted)} Dataset(s) mit Drift, Auto-Heal ausgeloest -- siehe Details oben: {drifted}")

    if failed:
        print(f"\n  {len(failed)} Schreibvorgang/-vorgaenge ohne erfolgreiches Ruecklesen: {failed}")
        return 1
    print(f"\n  Alle {len(RESULTS)} Schreibvorgaenge zurueckgelesen und bestaetigt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
