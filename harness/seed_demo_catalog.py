"""Seedt einen Demo-Katalog in Unternehmensgroesse -- mehrere Plattformen,
mehrere Datenbanken, mehrere hundert gepruefte Kanten.

WARUM diese Datei zusaetzlich zu `harness/seed_lineage_lab.py` existiert:
das Vier-Kanten-Labor (`probate_seedlab`) ist der BEWEIS -- je eine Kante
pro Zustand, per `harness/seedlab_verdicts.py` gegen ein Manifest
abgenommen. Es ist aber keine DEMO. Joel, 07.08.2026, woertlich:
*"firmen haben evt 1000 sachen... das hier wird bei 4 schon
unuebersichtlich"* und *"die DEMO!!!!! sie muss gut sein... ist sie aber
nicht!!!!"*. Bei vier Zeilen hat nichts an der Konsole einen Grund zu
existieren: Filter filtern nichts, der Katalogbaum hat einen Ast,
Sortierung ist sinnlos, Seitenaufteilung ueberfluessig
(`docs/werkbank-spec.md`, "Der Massstab").

Dieses Skript legt daneben -- in einem EIGENEN Namensraum, das Labor
bleibt unberuehrt -- einen Katalog an, der aussieht wie der eines echten
mittelgrossen Unternehmens:

  * vier Plattformen (postgres, kafka, snowflake, bigquery)
  * fuenf Datenbanken (Finance, Marketing, Ops, Product, HR)
  * vier Schemata je Datenbank (raw, staging, core, marts)
  * Domaenen, Besitzer und Glossarbegriffe auf einem guten Teil der Tabellen
  * mehrere hundert deklarierte Kanten, die der Ledger-Lauf tatsaechlich
    klassifiziert

--------------------------------------------------------------------------
DIE FUENF REGELN, DIE HIER GELTEN (alle aus bereits bezahlten Fehlern)
--------------------------------------------------------------------------

1. **Kein Zustandswort in einem Bezeichner.** Weder Tabellenname noch
   Query-ID noch Beschreibung darf sagen, wie die Kante darueber
   ausfaellt (`docs/entscheidungen/2026-08-07-seedlab-namen-ohne-etikett.md`
   und `...-seed-beschreibungen-ohne-etikett.md`). Sonst ist der
   Vier-Zustaende-Beleg zirkulaer: die Werkbank zeigt die URN direkt neben
   dem Urteil. `_assert_names_are_clean()` erzwingt das maschinell.

2. **Geseedet wird ausgewiesen** (`UEBERGABE.md` §7.3) -- hier auf drei
   Wegen: der Datenbank-Praefix `probate_demo_*` steht in JEDER URN, jede
   Beschreibung traegt den Offenlegungs-Praefix in eckigen Klammern, und
   Manifest wie Lauf-Artefakt tragen `seeded: true` samt Satz.

3. **Der Offenlegungs-Praefix darf nicht zitierfaehig sein**
   (`docs/entscheidungen/2026-08-07-seed-hinweis-nicht-zitierfaehig.md`).
   `probate/judge.py::_strip_disclosure_prefix` schneidet einen fuehrenden
   `[...]`-Block aus dem zitierfaehigen Korpus -- der Praefix hier hat
   deshalb GENAU diese Form, damit derselbe Mechanismus greift wie beim
   Labor. Er ist bewusst nicht anders formatiert.

4. **SDK-Emitter fuer Zeitreihen, nie rohes REST** (`UEBERGABE.md` Falle 23:
   derselbe Aufruf mit handgebautem `aspect.value` kam mit HTTP 200 zurueck
   und schrieb nichts). Gemessen 07.08. auf dieser Instanz:
   `emit_mcp` einzeln 71 ms/Bucket, `emit_mcps` gebuendelt **18 ms/Bucket**
   -- Faktor 4, deshalb gebuendelt.

5. **Nach dem Schreiben zurueckgelesen, sonst ist der Lauf gescheitert**
   (`UEBERGABE.md` Falle 21: GMS quittiert mit HTTP 200 und schreibt
   trotzdem nichts, wenn der Kafka-Broker unter ihm neu gestartet ist).
   Jeder Schreibschritt hier hat seine Rueckluse-Pruefung, Zeitreihen
   ueber die ROHABLAGE (`/aspects?action=getTimeseriesAspectValues`,
   Falle 14: `limit` ist Pflichtfeld), nicht ueber die ES-gestuetzte
   Aggregation (Falle 19: >75 s Verzug gemessen).

--------------------------------------------------------------------------
WIE DIE VIER ZUSTAENDE HIER ENTSTEHEN
--------------------------------------------------------------------------

`probate/ledger.py::classify_edges` urteilt pro Kante aus drei Signalen:
deklarierte Lineage, Nutzungs-Zeitfenster des ZIELS, und Query-Ko-Okkurrenz
(plus `queries_seen`, die Zahl der Queries, die den FOKUS ueberhaupt
beruehren). Daraus:

  confirmed  deklariert + Paar-Query + Ziel hat Nutzungsfenster
  dead       deklariert, Ziel hat Fenster, aber im Fenster kein Verkehr
             (oder: Verkehr, keine Paar-Query, und die Query-Quelle wurde
             nachweislich befragt -- `queries_seen > 0`)
  missing    Paar-Query, aber KEINE deklarierte Kante
  unknown    Ziel hat ueberhaupt keine Nutzungsfenster -- ODER Verkehr
             gemessen, aber die Query-Quelle ist leer (`queries_seen == 0`),
             dann ist die Kante schlicht nicht pruefbar

Der zweite `unknown`-Weg ist in einem echten Katalog der HAEUFIGSTE Fall
und deshalb hier bewusst stark vertreten: die meisten Unternehmen haben
Nutzungsstatistik, aber keine Query-Ingestion.

**Warum die Fokus-Menge nur die Ebenen `raw` und `core` umfasst:** die
Ko-Okkurrenz ist UNGERICHTET (`fetch_cooccurrence`-Docstring). Eine
Paar-Query ueber {A, B} laesst A in Bs Ko-Okkurrenz auftauchen und
umgekehrt. Waere B selbst ein Fokus, entstuende eine gespiegelte
`missing`-Kante B->A, die niemand gemeint hat -- fuer JEDE bestaetigte
Kante eine. Deshalb die harte Trennung: Fokusse sind `raw` und `core`,
Paar-Partner sind ausschliesslich `staging` und `marts`, und kein Dataset
ist beides. `_assert_focus_partner_disjoint()` erzwingt das.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # fuer `probate.*` bei Direktlauf

from datahub.emitter.mcp import MetadataChangeProposalWrapper  # noqa: E402
from datahub.emitter.rest_emitter import DatahubRestEmitter, EmitMode  # noqa: E402
from datahub.metadata.schema_classes import (  # noqa: E402
    DatasetUsageStatisticsClass,
    TimeWindowSizeClass,
)

from probate.gms import Gms, GmsError, _validate_urn  # noqa: E402

GMS_DEFAULT = "http://localhost:28080"
NAMESPACE_PREFIX = "probate_demo"
MANIFEST_PATH = Path("examples/demo-catalog-manifest.json")
ACTOR = "urn:li:corpuser:datahub"
STAMP = {"time": 1754300000000, "actor": ACTOR}
FAR_FUTURE_MS = 4_102_444_800_000  # 2100-01-01 UTC

# Offenlegung in Klammern -- exakt die Form, die
# `probate/judge.py::_DISCLOSURE_PREFIX_RE` aus dem zitierfaehigen Korpus
# schneidet (Regel 3 im Modul-Docstring).
DESC_PREFIX = "[probate-demo -- synthetische Demonstrationsdaten]"

SEEDED_STATEMENT = (
    "Kuenstlich eingespielte Demonstrationsdaten (harness/seed_demo_catalog.py), "
    "keine echte Warehouse-Nutzung. Alle Datenbanken beginnen mit "
    "'probate_demo_'; jede Tabellenbeschreibung traegt den Offenlegungs-Praefix."
)

# Zeitanker wie im Labor: der aktuelle Tag um Mitternacht UTC, NEU
# berechnet bei jedem Lauf. Ein fest verdrahtetes Kalenderdatum waere
# irgendwann aus dem rollenden 32-Tage-Fenster von
# `probate/ledger.py::USAGE_WINDOW_DAYS` herausgelaufen -- der Seeder
# haette weiter Exit 0 gemeldet ueber einem Katalog, in dem jede Kante zu
# `unknown` kollabiert ist (derselbe Fehler, den Fix-Runde 3 im Labor
# behoben hat).
USAGE_ANCHOR = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def days_ago_ms(n: int) -> int:
    return int((USAGE_ANCHOR - timedelta(days=n)).timestamp() * 1000)


# --- Plattformen, Datenbanken, Schemata ----------------------------------

PLATFORM_URNS = {
    "postgres": "urn:li:dataPlatform:postgres",
    "kafka": "urn:li:dataPlatform:kafka",
    "snowflake": "urn:li:dataPlatform:snowflake",
    "bigquery": "urn:li:dataPlatform:bigquery",
}

# Ebene -> (Schema-Name, moegliche Plattformen). Die Ebenen sind zwei
# unabhaengige Zwei-Schritt-Strecken (raw->staging und core->marts), nicht
# eine Vier-Schritt-Kette: siehe Modul-Docstring, Abschnitt "Warum die
# Fokus-Menge nur raw und core umfasst".
LAYERS = {
    "raw": ("raw", ("postgres", "kafka")),
    "staging": ("staging", ("snowflake",)),
    "core": ("core", ("snowflake", "bigquery")),
    "marts": ("marts", ("snowflake", "bigquery")),
}

FOCUS_LAYERS = ("raw", "core")
PARTNER_LAYERS = ("staging", "marts")
EDGE_HOPS = {"raw": "staging", "core": "marts"}

DOMAINS = ("finance", "marketing", "ops", "product", "hr")

# Wie viele Tabellen je Datenbank und Ebene bei Skala "full". Bewusst
# ungleich verteilt -- ein Katalog, in dem jede Domaene gleich gross ist,
# sieht gestellt aus.
FULL_SIZES: dict[str, dict[str, int]] = {
    "finance":   {"raw": 40, "staging": 42, "core": 38, "marts": 26},
    "marketing": {"raw": 36, "staging": 38, "core": 36, "marts": 26},
    "ops":       {"raw": 34, "staging": 34, "core": 32, "marts": 22},
    "product":   {"raw": 34, "staging": 36, "core": 32, "marts": 22},
    "hr":        {"raw": 22, "staging": 22, "core": 22, "marts": 16},
}
# Kleine Stufe zum Vormessen -- gleiche Struktur, gleiche Codepfade.
SMOKE_SIZES: dict[str, dict[str, int]] = {
    d: {layer: max(2, n // 12) for layer, n in sizes.items()}
    for d, sizes in FULL_SIZES.items()
}
SCALES = {"full": FULL_SIZES, "smoke": SMOKE_SIZES}


# --- Namensbausteine ------------------------------------------------------
#
# Regel 1 (Modul-Docstring): ein Tabellenname sagt, WAS in der Tabelle
# steht -- nie, wie die Kante darueber ausfaellt. Verboten sind
# insbesondere dead/stale/unused/orphan/abandoned/confirmed/missing/
# unknown/deprecated sowie test/demo/tmp (letztere markieren eine Tabelle
# als Wegwerf-Artefakt und deuten damit auf duenne Nutzung).
FORBIDDEN_NAME_TOKENS = (
    "dead", "stale", "unused", "orphan", "abandoned", "deprecated",
    "confirmed", "missing", "unknown", "obsolete", "legacy", "todo",
    "test", "demo", "dummy", "sample", "fixture", "tmp", "scratch",
)

RAW_ENTITIES: dict[str, tuple[str, ...]] = {
    "finance": ("gl_entries", "journal_lines", "invoices", "payments", "refunds",
                "credit_notes", "bank_transactions", "fx_rates", "cost_centers",
                "vendor_bills", "tax_codes", "budget_lines"),
    "marketing": ("ad_clicks", "ad_impressions", "email_sends", "email_opens",
                  "campaign_members", "landing_page_hits", "form_submissions",
                  "utm_touches", "newsletter_signups", "affiliate_referrals",
                  "push_deliveries", "social_mentions"),
    "ops": ("shipments", "inventory_moves", "warehouse_picks", "carrier_scans",
            "returns", "support_tickets", "sla_breaches", "delivery_attempts",
            "stock_counts", "purchase_orders", "route_legs", "packing_slips"),
    "product": ("checkout_events", "session_starts", "page_views", "feature_flags",
                "app_crashes", "search_queries", "cart_updates", "wishlist_adds",
                "onboarding_steps", "push_permissions", "review_submissions",
                "subscription_changes"),
    "hr": ("time_entries", "absences", "applications", "interview_feedback",
           "payroll_runs", "training_records", "org_assignments", "badge_swipes"),
}

RAW_SUFFIXES = ("", "_log", "_stream", "_events", "_journal", "_feed",
                "_eu", "_us", "_apac", "_intraday", "_hourly", "_v2")

STG_SOURCES = ("stripe", "shopify", "salesforce", "netsuite", "hubspot",
               "zendesk", "workday", "segment", "braze", "sap", "adyen",
               "mixpanel", "jira", "greenhouse", "klaviyo")

CORE_DIMENSIONS: dict[str, tuple[str, ...]] = {
    "finance": ("account", "cost_center", "vendor", "currency", "fiscal_period",
                "entity", "tax_jurisdiction"),
    "marketing": ("campaign", "channel", "audience_segment", "creative",
                  "landing_page", "partner"),
    "ops": ("warehouse", "carrier", "sku", "route", "supplier", "service_level"),
    "product": ("customer", "product", "device", "plan", "feature", "cohort"),
    "hr": ("employee", "department", "job_family", "location", "pay_grade"),
}
CORE_FACTS: dict[str, tuple[str, ...]] = {
    "finance": ("gl_postings", "revenue", "receivables", "payables", "cash_flow",
                "margin", "write_offs"),
    "marketing": ("ad_spend", "attribution_touches", "email_engagement",
                  "lead_pipeline", "campaign_cost", "audience_reach"),
    "ops": ("shipment_legs", "inventory_balance", "returns", "picking_time",
            "sla_compliance", "carrier_cost"),
    "product": ("orders", "sessions", "feature_usage", "subscriptions",
                "checkout_funnel", "search_results"),
    "hr": ("headcount", "attrition", "hiring_pipeline", "absence_days",
           "payroll_cost"),
}
FACT_GRAINS = ("daily", "weekly", "monthly", "hourly", "by_region", "by_segment",
               "by_channel", "by_store", "snapshot", "rolling_28d")

MART_TOPICS: dict[str, tuple[str, ...]] = {
    "finance": ("close_pack", "revenue_bridge", "cost_control", "investor_reporting",
                "working_capital", "audit_trail"),
    "marketing": ("attribution", "channel_mix", "lifecycle", "spend_efficiency",
                  "brand_reach", "lead_quality"),
    "ops": ("delivery_performance", "network_load", "supplier_scorecard",
            "returns_analysis", "capacity_plan"),
    "product": ("growth", "retention", "activation", "pricing", "roadmap_signals",
                "customer_health"),
    "hr": ("workforce_plan", "talent_pipeline", "compensation", "engagement"),
}
MART_LENSES = ("overview", "by_region", "by_segment", "monthly", "quarterly",
               "exec", "detail", "trend", "by_market", "board")


# --- Beschreibungs-Bausteine ---------------------------------------------
#
# Regel aus `docs/entscheidungen/2026-08-07-seed-beschreibungen-ohne-etikett.md`,
# hier unveraendert uebernommen: eine Beschreibung darf sagen WAS eine
# Tabelle enthaelt und WARUM sie dem Geschaeft wichtig ist. Sie darf NICHT
# sagen oder andeuten: wie die Daten technisch ihre Konsumenten erreichen
# (Pipeline vs. Ad-hoc-Query vs. benanntes Dashboard), ob Dokumentation
# oder Lineage existiert, ob ein Konsument bekannt ist, ob die Tabelle noch
# genutzt/gepflegt/aufgegeben wird, oder wie aktuell der letzte Zugriff war
# -- das sind exakt die Observablen, die das Werkzeug selbst herleiten soll.
LAYER_DESC = {
    "raw": (
        "Unveraenderte Einzelereignisse aus dem Quellsystem, ohne Filterung "
        "oder Aggregation."
    ),
    "staging": (
        "Vereinheitlichte Fassung der Quelldaten: Typen normalisiert, "
        "Schluessel vereinheitlicht, Duplikate nach fachlichem Schluessel "
        "zusammengefuehrt."
    ),
    "core": (
        "Modellierte Kernschicht des Warehouse mit stabilen fachlichen "
        "Schluesseln und Historisierung."
    ),
    "marts": (
        "Fachlich zugeschnittene Auswertungsschicht fuer die "
        "Bereichssteuerung."
    ),
}
DOMAIN_DESC = {
    "finance": "Rechnungswesen und externe Berichterstattung.",
    "marketing": "Kampagnensteuerung und Budgetverteilung.",
    "ops": "Logistik, Lager und Lieferfaehigkeit.",
    "product": "Produktnutzung und Kundenlebenszyklus.",
    "hr": "Personalbestand und Personalkosten.",
}
RELEVANCE = (
    "Bestandteil der monatlichen Bereichsberichterstattung.",
    "Grundlage der Quartalsplanung des Bereichs.",
    "Eine der Kennzahlen im Zielsystem der Bereichsleitung.",
    "Teil der Datengrundlage fuer die Jahresplanung.",
    "Fachlich abgestimmt mit dem jeweiligen Fachbereich.",
    "",  # nicht jede Tabelle traegt eine Relevanz-Aussage
    "",
)

DOMAIN_LABELS = {
    "finance": "Finance", "marketing": "Marketing", "ops": "Operations",
    "product": "Product", "hr": "People",
}
DOMAIN_DEFS = {
    f"urn:li:domain:{NAMESPACE_PREFIX}.{d}": {
        "name": DOMAIN_LABELS[d], "description": DOMAIN_DESC[d]
    }
    for d in DOMAINS
}

OWNERS_BY_DOMAIN: dict[str, tuple[tuple[str, str], ...]] = {
    "finance": (("urn:li:corpuser:m.keller", "DATAOWNER"),
                ("urn:li:corpuser:finance.reporting", "BUSINESS_OWNER"),
                ("urn:li:corpuser:s.brunner", "TECHNICAL_OWNER")),
    "marketing": (("urn:li:corpuser:growth.analytics", "BUSINESS_OWNER"),
                  ("urn:li:corpuser:l.frei", "TECHNICAL_OWNER")),
    "ops": (("urn:li:corpuser:ops.data", "DATAOWNER"),
            ("urn:li:corpuser:r.huber", "TECHNICAL_OWNER")),
    "product": (("urn:li:corpuser:p.moser", "DATAOWNER"),
                ("urn:li:corpuser:product.analytics", "BUSINESS_OWNER")),
    "hr": (("urn:li:corpuser:people.ops", "BUSINESS_OWNER"),),
}

TERM_DEFS = {
    f"urn:li:glossaryTerm:{NAMESPACE_PREFIX}.hauptbuch": {
        "name": "Hauptbuch",
        "definition": "Zentrales Buchungsjournal aller Geschaeftsvorfaelle."},
    f"urn:li:glossaryTerm:{NAMESPACE_PREFIX}.umsatz": {
        "name": "Nettoumsatz",
        "definition": "Umsatz nach Abzug von Retouren, Rabatten und Umsatzsteuer."},
    f"urn:li:glossaryTerm:{NAMESPACE_PREFIX}.attribution": {
        "name": "Attribution",
        "definition": "Zuordnung eines Abschlusses zu den vorangegangenen Kontaktpunkten."},
    f"urn:li:glossaryTerm:{NAMESPACE_PREFIX}.liefertreue": {
        "name": "Liefertreue",
        "definition": "Anteil der Sendungen, die im zugesagten Zeitfenster ankommen."},
    f"urn:li:glossaryTerm:{NAMESPACE_PREFIX}.clv": {
        "name": "Customer Lifetime Value",
        "definition": "Prognostizierter Gesamtumsatz eines Kunden ueber die Kundenbeziehung."},
    f"urn:li:glossaryTerm:{NAMESPACE_PREFIX}.fluktuation": {
        "name": "Fluktuation",
        "definition": "Anteil der Austritte gemessen am durchschnittlichen Personalbestand."},
}
TERMS_BY_DOMAIN = {
    "finance": (f"urn:li:glossaryTerm:{NAMESPACE_PREFIX}.hauptbuch",
                f"urn:li:glossaryTerm:{NAMESPACE_PREFIX}.umsatz"),
    "marketing": (f"urn:li:glossaryTerm:{NAMESPACE_PREFIX}.attribution",),
    "ops": (f"urn:li:glossaryTerm:{NAMESPACE_PREFIX}.liefertreue",),
    "product": (f"urn:li:glossaryTerm:{NAMESPACE_PREFIX}.clv",),
    "hr": (f"urn:li:glossaryTerm:{NAMESPACE_PREFIX}.fluktuation",),
}


# --- Nutzungs-Bucket-Profile ---------------------------------------------
#
# Alle Fenster liegen INNERHALB der 32 Tage, die
# `probate/ledger.py::USAGE_WINDOW_DAYS` abfragt -- ausserhalb liegende
# Buckets wuerden nie gelesen und waeren verschwendete Schreibzeit.

def _fresh(rng: random.Random) -> list[tuple[int, int, int]]:
    """Regelmaessiger Verkehr bis heute."""
    out = []
    for d in (0, 1, 3, 6, 11)[: rng.choice((4, 5, 5))]:
        out.append((days_ago_ms(d), rng.randint(8, 140), rng.randint(1, 14)))
    return out


def _traffic(rng: random.Random) -> list[tuple[int, int, int]]:
    """Verkehr vorhanden, aber duenner -- fuer die Faelle, in denen die
    Query-Quelle das Urteil traegt, nicht die Nutzungszahl."""
    return [(days_ago_ms(d), rng.randint(3, 40), rng.randint(1, 6))
            for d in (1, 5, 12, 19)]


def _zero_in_window(_rng: random.Random) -> list[tuple[int, int, int]]:
    """Wir haben hingesehen, und es war nichts da. Fuenf echte Messfenster
    mit gemessener Null -- NICHT dasselbe wie 'keine Fenster'."""
    return [(days_ago_ms(d), 0, 0) for d in (31, 24, 17, 10, 3)]


def _none(_rng: random.Random) -> list[tuple[int, int, int]]:
    return []


USAGE_PROFILES = {"fresh": _fresh, "traffic": _traffic,
                  "zero": _zero_in_window, "none": _none}


# --- Fokus-Profile: wie die Zustands-Mischung zustande kommt --------------
#
# Verteilung bewusst NICHT gleich: in einem echten Katalog ist das Meiste
# bestaetigt, ein spuerbarer Anteil unbekannt (keine Query-Ingestion --
# der haeufigste Fall der Wirklichkeit), einiges tot, weniges fehlend.
# Eine Demo, in der alle vier Zustaende zu je 25 % vorkommen, sieht
# gestellt aus.
#
# Jedes Profil beschreibt einen FOKUS (Upstream) mit seinen Zielen:
#   pair_query : bekommt das Ziel eine Paar-Query? (-> confirmed)
#   usage      : welches Bucket-Profil bekommt das Ziel?
#   extra_missing: zusaetzlich eine Query auf ein NICHT deklariertes Ziel
@dataclass(frozen=True)
class FocusProfile:
    name: str
    weight: int
    targets: int                    # wie viele deklarierte Ziele
    pair_query_for: tuple[bool, ...]  # je Ziel: Paar-Query ja/nein
    usage_for: tuple[str, ...]        # je Ziel: Bucket-Profil
    extra_missing: int = 0            # zusaetzliche undeklarierte Paar-Ziele


FOCUS_PROFILES: tuple[FocusProfile, ...] = (
    # Der Normalfall eines gepflegten Bereichs: alles gedeckt.
    FocusProfile("versorgt_1", 20, 1, (True,), ("fresh",)),
    FocusProfile("versorgt_2", 17, 2, (True, True), ("fresh", "fresh")),
    FocusProfile("versorgt_3", 6, 3, (True, True, True), ("fresh", "fresh", "fresh")),
    # Ein Ziel gedeckt, eines nicht mehr belegt -- die Query-Quelle wurde
    # befragt und kennt die zweite Kante nicht (-> dead, starker Beleg).
    FocusProfile("teilweise", 6, 2, (True, False), ("fresh", "traffic")),
    FocusProfile("teilweise_3", 2, 3, (True, False, False),
                 ("fresh", "traffic", "traffic")),
    # Ohne Query-Ingestion: Verkehr gemessen, Kante nicht pruefbar (-> unknown).
    FocusProfile("ohne_query_1", 7, 1, (False,), ("traffic",)),
    FocusProfile("ohne_query_2", 4, 2, (False, False), ("traffic", "traffic")),
    # Ziel ohne jedes Nutzungsfenster -- keine Daten ist nicht null Verkehr.
    # Der Auftrag nennt das ausdruecklich "den haeufigsten Fall in der
    # Wirklichkeit", deshalb der schwerste `unknown`-Zweig.
    FocusProfile("ohne_messung_1", 12, 1, (False,), ("none",)),
    FocusProfile("ohne_messung_2", 7, 2, (False, False), ("none", "none")),
    # Fenster vorhanden, Verkehr darin durchgehend null (-> dead).
    #
    # Gewicht bewusst hoeher als bei `teilweise` (Messung 07.08.: 63 der 81
    # toten Kanten waren vorher vom Typ "Verkehr da, Paar-Query fehlt").
    # Beide Wege sind richtig und beide gehoeren in die Demo -- aber der
    # zweite liest sich in der TABELLE widerspruechlich: Zustand "tot" neben
    # "zuletzt belegt: gestern, 68 Abfragen". Der Beleg der Kante erklaert
    # das (die Zahl gehoert der TABELLE, nicht der Kante), nur steht die
    # Erklaerung in der Detailspalte und der Widerspruch in der Zeile. Der
    # selbsterklaerende Fall -- fuenf Messfenster, in allen null -- soll
    # deshalb der haeufigere sein.
    FocusProfile("still_1", 9, 1, (False,), ("zero",)),
    FocusProfile("still_2", 6, 2, (False, False), ("zero", "zero")),
    # Eine Query beruehrt ein Ziel, das der Katalog nicht kennt (-> missing).
    FocusProfile("undeklariert", 5, 1, (True,), ("fresh",), extra_missing=1),
    FocusProfile("undeklariert_nur", 3, 0, (), (), extra_missing=1),
)


# --- Der Plan (rein, ohne Netz -- deshalb testbar) ------------------------


@dataclass
class DatasetSpec:
    urn: str
    platform: str
    database: str
    schema: str
    table: str
    domain: str
    layer: str
    description: str
    owners: tuple[tuple[str, str], ...] = ()
    terms: tuple[str, ...] = ()
    usage: tuple[tuple[int, int, int], ...] = ()


@dataclass
class EdgeSpec:
    upstream: str
    downstream: str
    declared: bool
    pair_query: bool
    expected_state: str


@dataclass
class Plan:
    datasets: list[DatasetSpec] = field(default_factory=list)
    edges: list[EdgeSpec] = field(default_factory=list)
    queries: list[dict] = field(default_factory=list)  # {urn, subjects:[a,b]}
    focuses: list[str] = field(default_factory=list)

    @property
    def by_urn(self) -> dict[str, DatasetSpec]:
        return {d.urn: d for d in self.datasets}


def dataset_urn(platform: str, domain: str, schema: str, table: str) -> str:
    return (f"urn:li:dataset:({PLATFORM_URNS[platform]},"
            f"{NAMESPACE_PREFIX}_{domain}.{schema}.{table},PROD)")


def _unique(names: Iterable[str], want: int, rng: random.Random) -> list[str]:
    """Aus einem Generator so viele verschiedene Namen ziehen wie noetig.
    Ein Zaehl-Suffix ist der letzte Ausweg, nicht der Normalfall -- die
    Vokabulare sind gross genug, dass er selten greift."""
    seen: list[str] = []
    pool = list(names)
    rng.shuffle(pool)
    for n in pool:
        if n not in seen:
            seen.append(n)
        if len(seen) >= want:
            return seen
    i = 2
    while len(seen) < want:
        for n in pool:
            cand = f"{n}_{i}"
            if cand not in seen:
                seen.append(cand)
            if len(seen) >= want:
                break
        i += 1
    return seen


def _names_for(domain: str, layer: str, want: int, rng: random.Random) -> list[str]:
    if layer == "raw":
        pool = [f"{e}{s}" for e in RAW_ENTITIES[domain] for s in RAW_SUFFIXES]
    elif layer == "staging":
        pool = [f"stg_{src}_{e}" for src in STG_SOURCES
                for e in RAW_ENTITIES[domain]]
    elif layer == "core":
        pool = ([f"dim_{d}" for d in CORE_DIMENSIONS[domain]]
                + [f"fct_{f}_{g}" for f in CORE_FACTS[domain] for g in FACT_GRAINS])
    else:
        pool = [f"mart_{t}_{lens}" for t in MART_TOPICS[domain] for lens in MART_LENSES]
    return _unique(pool, want, rng)


def _description(domain: str, layer: str, table: str, rng: random.Random) -> str:
    parts = [LAYER_DESC[layer], DOMAIN_DESC[domain]]
    rel = rng.choice(RELEVANCE)
    if rel:
        parts.append(rel)
    return f"{DESC_PREFIX} {' '.join(parts)}"


def _assert_names_are_clean(plan: Plan) -> None:
    """Regel 1 maschinell: kein Bezeichner verraet den Kanten-Zustand.

    Geprueft werden Tabellennamen UND Query-IDs -- beide stehen in der
    Werkbank direkt neben dem Urteil. Der Datenbank-Praefix
    `probate_demo_*` ist ausgenommen: er traegt kein Urteil, er ist die
    Offenlegung (Regel 2), und er steht auf JEDER Zeile gleich -- damit
    unterscheidet er keine Kante von einer anderen.
    """
    bad: list[str] = []
    for d in plan.datasets:
        low = d.table.lower()
        for tok in FORBIDDEN_NAME_TOKENS:
            if tok in low:
                bad.append(f"tabelle {d.table}: enthaelt {tok!r}")
    for q in plan.queries:
        low = q["urn"].lower().replace(NAMESPACE_PREFIX, "")
        for tok in FORBIDDEN_NAME_TOKENS:
            if tok in low:
                bad.append(f"query {q['urn']}: enthaelt {tok!r}")
    if bad:
        raise ValueError("Bezeichner verraten den Zustand: " + "; ".join(bad[:10]))


def _assert_focus_partner_disjoint(plan: Plan) -> None:
    """Kein Dataset ist gleichzeitig Fokus und Paar-Query-Partner.

    Sonst entstuende zu jeder bestaetigten Kante A->B eine gespiegelte
    `missing`-Kante B->A, weil die Ko-Okkurrenz ungerichtet ist
    (`fetch_cooccurrence`-Docstring). Siehe Modul-Docstring.
    """
    focuses = set(plan.focuses)
    partners = {s for q in plan.queries for s in q["subjects"]}
    overlap = focuses & partners
    # Der Fokus SELBST steht in seiner Paar-Query -- das ist der Zweck.
    # Verboten ist nur, dass ein PARTNER (die andere Seite) ein Fokus ist.
    real_overlap = set()
    for q in plan.queries:
        a, b = q["subjects"][0], q["subjects"][1]
        if a in focuses and b in focuses:
            real_overlap.add(f"{a} + {b}")
    if real_overlap:
        raise ValueError(
            "Paar-Query zwischen zwei Fokussen -- erzeugt gespiegelte "
            f"missing-Kanten: {sorted(real_overlap)[:5]}")
    _ = overlap


def _expected_state(pair_query: bool, usage: str, focus_has_query: bool,
                    declared: bool) -> str:
    """Die Erwartung dieses Labors -- die Gegenprobe dazu ist der echte
    Lauf (`harness/run_demo_ledger.py`), nicht diese Funktion. Sie
    spiegelt `probate/ledger.py::classify_edges` wider und existiert, damit
    ein Abweichen auffaellt statt unbemerkt zu bleiben."""
    if not declared:
        return "missing"
    if usage == "none":
        return "unknown"
    if pair_query:
        return "confirmed"
    if usage == "zero":
        return "dead"          # Fenster da, im Fenster kein Verkehr
    if focus_has_query:
        return "dead"          # Query-Quelle befragt, Paar nicht gefunden
    return "unknown"           # Verkehr da, aber Query-Quelle leer


def build_plan(sizes: dict[str, dict[str, int]], seed: int = 20260807) -> Plan:
    """Der ganze Katalog als reine Datenstruktur -- kein Netz, kein GMS.

    Deterministisch ueber `seed`: derselbe Seed ergibt denselben Katalog,
    sonst waere eine Wiederholungsmessung keine Wiederholung.

    Reihenfolge ist Absicht und war ein Fehler wert: die erste Fassung
    berechnete `expected_state` aus dem Bucket-Profil, das das FOKUS-Profil
    fuer dieses Ziel VORSAH. Ziele werden aber reihum vergeben und koennen
    mehrere Upstreams haben (in einem echten Warehouse der Normalfall) --
    das zweite Fokus-Profil fand das Ziel dann bereits belegt, schrieb
    seine Buckets nicht mehr, notierte aber trotzdem die Erwartung seines
    eigenen Profils. Das Manifest haette dann eine Erwartung getragen, die
    die Daten nicht hergeben -- genau die Sorte Behauptung ohne Beleg,
    gegen die dieses Projekt antritt.

    Jetzt in drei Phasen: erst die Zuordnung Fokus -> Ziele, dann das
    Bucket-Profil je ZIEL (das erste greift, spaetere lesen es), und
    ZULETZT der erwartete Zustand -- aus dem tatsaechlichen Profil des
    Ziels und aus `queries_seen` des ganzen Fokus, nicht aus der Absicht.
    """
    rng = random.Random(seed)
    plan = Plan()

    # 1. Tabellen
    by_domain_layer: dict[tuple[str, str], list[DatasetSpec]] = {}
    for domain in DOMAINS:
        for layer in ("raw", "staging", "core", "marts"):
            want = sizes[domain][layer]
            schema, platforms = LAYERS[layer]
            names = _names_for(domain, layer, want, rng)
            specs = []
            for i, table in enumerate(names):
                platform = platforms[i % len(platforms)]
                spec = DatasetSpec(
                    urn=dataset_urn(platform, domain, schema, table),
                    platform=platform,
                    database=f"{NAMESPACE_PREFIX}_{domain}",
                    schema=schema, table=table, domain=domain, layer=layer,
                    description=_description(domain, layer, table, rng),
                )
                # Domaene auf allen, Besitzer auf gut zwei Dritteln, Glossar
                # auf den fachlich tragenden Ebenen -- wie in einem echten
                # Katalog, in dem niemand jede Zwischentabelle vertritt.
                if rng.random() < 0.68:
                    owners = OWNERS_BY_DOMAIN[domain]
                    spec.owners = (owners[rng.randrange(len(owners))],)
                if layer in ("core", "marts") and rng.random() < 0.55:
                    spec.terms = (rng.choice(TERMS_BY_DOMAIN[domain]),)
                specs.append(spec)
            by_domain_layer[(domain, layer)] = specs
            plan.datasets.extend(specs)

    # 2. Zuordnung Fokus -> Ziele (noch ohne Zustand)
    weights = [p.weight for p in FOCUS_PROFILES]
    # Ziel-URN -> Name des Bucket-Profils. Das ERSTE Fokus-Profil, das ein
    # Ziel belegt, bestimmt es; alle spaeteren Kanten auf dasselbe Ziel
    # LESEN es (statt eine Erwartung zu notieren, die die Daten nicht
    # hergeben -- siehe Docstring).
    usage_profile_of: dict[str, str] = {}
    assignments: list[tuple[DatasetSpec, FocusProfile, list[DatasetSpec]]] = []

    for domain in DOMAINS:
        for focus_layer in FOCUS_LAYERS:
            target_layer = EDGE_HOPS[focus_layer]
            sources = list(by_domain_layer[(domain, focus_layer)])
            targets = list(by_domain_layer[(domain, target_layer)])
            if not targets:
                continue
            # Ziele werden reihum vergeben, damit nicht dieselben drei
            # Tabellen alle Kanten abbekommen. Ein Ziel mit mehreren
            # Upstreams ist dabei kein Fehler, sondern der Normalfall eines
            # echten Warehouse -- `_lineage()` fuehrt sie in EINEM Aspekt
            # zusammen.
            t_i = 0
            for src in sources:
                profile = rng.choices(FOCUS_PROFILES, weights=weights, k=1)[0]
                n_needed = profile.targets + profile.extra_missing
                if n_needed == 0:
                    continue
                chosen: list[DatasetSpec] = []
                for _ in range(n_needed):
                    chosen.append(targets[t_i % len(targets)])
                    t_i += 1
                # Zweimal dasselbe Ziel fuer denselben Fokus waere keine
                # zweite Kante, sondern dieselbe -- dann faellt dieser
                # Fokus aus.
                if len({c.urn for c in chosen}) != len(chosen):
                    continue
                for i in range(profile.targets):
                    tgt = chosen[i]
                    usage_profile_of.setdefault(tgt.urn, profile.usage_for[i])
                for j in range(profile.extra_missing):
                    tgt = chosen[profile.targets + j]
                    # Ein undeklariertes Ziel braucht Nutzungsfenster,
                    # sonst waere die Kante `unknown` statt `missing`.
                    usage_profile_of.setdefault(tgt.urn, "fresh")
                plan.focuses.append(src.urn)
                assignments.append((src, profile, chosen))

    # 3. Bucket-Profil je ZIEL festschreiben -- eine Wahrheit pro Tabelle.
    by_urn = plan.by_urn
    for urn, prof_name in usage_profile_of.items():
        by_urn[urn].usage = tuple(USAGE_PROFILES[prof_name](rng))

    # 4. Zustand ableiten -- aus dem TATSAECHLICHEN Profil des Ziels und
    #    aus `queries_seen` des ganzen Fokus (jede Paar-Query des Fokus
    #    zaehlt, auch die eines anderen Ziels).
    for src, profile, chosen in assignments:
        focus_has_query = (any(profile.pair_query_for[:profile.targets])
                           or profile.extra_missing > 0)
        for i in range(profile.targets):
            tgt = chosen[i]
            pair = profile.pair_query_for[i]
            actual = usage_profile_of[tgt.urn]
            plan.edges.append(EdgeSpec(
                upstream=src.urn, downstream=tgt.urn, declared=True,
                pair_query=pair,
                expected_state=_expected_state(pair, actual, focus_has_query, True)))
            if pair:
                plan.queries.append(_query_record(src, tgt, "build"))
        for j in range(profile.extra_missing):
            tgt = chosen[profile.targets + j]
            plan.edges.append(EdgeSpec(
                upstream=src.urn, downstream=tgt.urn, declared=False,
                pair_query=True, expected_state="missing"))
            plan.queries.append(_query_record(src, tgt, "load"))

    _assert_names_are_clean(plan)
    _assert_focus_partner_disjoint(plan)
    _assert_no_duplicate_queries(plan)
    return plan


def _assert_no_duplicate_queries(plan: Plan) -> None:
    """Zwei Query-Entitaeten mit derselben URN waeren eine, nicht zwei --
    der zweite Schreibvorgang ersetzt den ersten (v3-Semantik), und das
    Manifest behauptete danach einen Beleg, den es nicht mehr gibt."""
    seen: set[str] = set()
    dupes: list[str] = []
    for q in plan.queries:
        if q["urn"] in seen:
            dupes.append(q["urn"])
        seen.add(q["urn"])
    if dupes:
        raise ValueError(f"doppelte Query-URNs: {sorted(set(dupes))[:5]}")


def _query_record(src: DatasetSpec, tgt: DatasetSpec, verb: str) -> dict:
    """Die Query-ID benennt den VORGANG, nie den Kanten-Zustand (Regel 1 --
    `probate/ledger.py` schreibt die Query-URN als Beleg in jedes Urteil,
    sie steht damit woertlich neben dem Wort, das sie erst herleiten soll)."""
    qid = (f"{NAMESPACE_PREFIX}-{verb}-{src.domain}-"
           f"{src.table[:34]}-{tgt.table[:34]}")
    return {
        "urn": f"urn:li:query:{qid}",
        "subjects": [src.urn, tgt.urn],
        "sql": (f"INSERT INTO {tgt.database}.{tgt.schema}.{tgt.table} "
                f"SELECT * FROM {src.database}.{src.schema}.{src.table}"),
    }


def plan_summary(plan: Plan) -> dict:
    states: dict[str, int] = {}
    for e in plan.edges:
        states[e.expected_state] = states.get(e.expected_state, 0) + 1
    platforms: dict[str, int] = {}
    databases: dict[str, int] = {}
    for d in plan.datasets:
        platforms[d.platform] = platforms.get(d.platform, 0) + 1
        databases[d.database] = databases.get(d.database, 0) + 1
    return {
        "datasets": len(plan.datasets),
        "edges": len(plan.edges),
        "declared_edges": sum(1 for e in plan.edges if e.declared),
        "queries": len(plan.queries),
        "focuses": len(plan.focuses),
        "usage_buckets": sum(len(d.usage) for d in plan.datasets),
        "datasets_with_usage": sum(1 for d in plan.datasets if d.usage),
        "datasets_with_owner": sum(1 for d in plan.datasets if d.owners),
        "datasets_with_terms": sum(1 for d in plan.datasets if d.terms),
        "platforms": platforms,
        "databases": databases,
        "expected_states": states,
        "expected_state_share": {
            k: round(v / max(1, len(plan.edges)), 3) for k, v in sorted(states.items())
        },
    }


# --- Schreiben ------------------------------------------------------------


@dataclass
class Step:
    what: str
    seconds: float
    ok: bool
    detail: str = ""


def _chunks(items: Sequence, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _raw_usage_rows(gms: Gms, urn: str) -> list[dict]:
    """Rohablage statt Aggregation -- Falle 19 (ES-Aggregation hinkte >75 s
    nach), Falle 14 (`limit` ist Pflichtfeld)."""
    _validate_urn(urn)
    payload = {"urn": urn, "entity": "dataset", "aspect": "datasetUsageStatistics",
               "startTimeMillis": 0, "endTimeMillis": FAR_FUTURE_MS, "limit": 500}
    status, body = gms._send(
        "POST", f"{gms.base}/aspects?action=getTimeseriesAspectValues", payload)
    if status != 200 or not isinstance(body, dict):
        raise GmsError(f"getTimeseriesAspectValues HTTP {status}: {str(body)[:200]}")
    return ((body.get("value") or {}).get("values")) or []


def purge_usage(gms: Gms, urns: Sequence[str]) -> int:
    """Volle Zeitreihen-Historie weg, BEVOR neu geschrieben wird.

    Ohne das ist ein zweiter Lauf an einem anderen Kalendertag nicht
    idempotent: die Buckets haengen an `USAGE_ANCHOR`, alte Zeilen blieben
    daneben liegen. `gms.delete_aspect` taugt dafuer nicht -- bei
    Zeitreihen entfernt die generische DELETE-Route nur die juengste Zeile
    (`harness/seed_lineage_lab.py`, Fix-Runde 3)."""
    rows = 0
    for urn in urns:
        _validate_urn(urn)
        status, body = gms._send(
            "POST", f"{gms.base}/entities?action=delete",
            {"urn": urn, "aspectName": "datasetUsageStatistics",
             "startTimeMillis": 0, "endTimeMillis": FAR_FUTURE_MS})
        if status != 200:
            raise GmsError(f"usage-purge {urn} HTTP {status}: {str(body)[:200]}")
        rows += (body or {}).get("value", {}).get("timeseriesRows", 0)
    return rows


def write_plan(gms: Gms, emitter: DatahubRestEmitter, plan: Plan,
               batch: int = 200, usage_batch: int = 400,
               verbose: bool = True) -> list[Step]:
    """Alle Schreibvorgaenge, jeder mit seiner Zeitmessung. Rueckluse
    passiert getrennt in `verify_plan` -- nach einer Wartezeit, weil der
    Graph-/Suchindex Writes nachhinkt (Falle 15)."""
    steps: list[Step] = []

    def step(what: str, fn) -> None:
        t0 = time.perf_counter()
        detail = fn() or ""
        steps.append(Step(what, round(time.perf_counter() - t0, 2), True, detail))
        if verbose:
            print(f"  {what:<44} {steps[-1].seconds:>7.2f}s  {detail}")

    def _domains():
        gms.upsert("domain", [
            {"urn": urn, "domainProperties": {"value": {
                "name": d["name"], "description": d["description"]}}}
            for urn, d in DOMAIN_DEFS.items()])
        return f"{len(DOMAIN_DEFS)} Domaenen"

    def _terms():
        gms.upsert("glossaryTerm", [
            {"urn": urn, "glossaryTermInfo": {"value": {
                "name": t["name"], "definition": t["definition"],
                "termSource": "INTERNAL"}}}
            for urn, t in TERM_DEFS.items()])
        return f"{len(TERM_DEFS)} Begriffe"

    def _datasets():
        n = 0
        for group in _chunks(plan.datasets, batch):
            gms.upsert("dataset", [
                {"urn": d.urn, "datasetProperties": {"value": {
                    "name": d.table, "qualifiedName": f"{d.database}.{d.schema}.{d.table}",
                    "description": d.description}}}
                for d in group])
            n += len(group)
        return f"{n} Tabellen"

    def _governance():
        with_gov = [d for d in plan.datasets if d.owners or d.terms or d.domain]
        for group in _chunks(with_gov, batch):
            records = []
            for d in group:
                rec: dict[str, Any] = {"urn": d.urn}
                rec["domains"] = {"value": {"domains": [
                    f"urn:li:domain:{NAMESPACE_PREFIX}.{d.domain}"]}}
                if d.owners:
                    rec["ownership"] = {"value": {"owners": [
                        {"owner": o, "type": t} for o, t in d.owners]}}
                if d.terms:
                    rec["glossaryTerms"] = {"value": {
                        "terms": [{"urn": t} for t in d.terms],
                        "auditStamp": STAMP}}
                records.append(rec)
            gms.upsert("dataset", records)
        return f"{len(with_gov)} Tabellen mit Domaene/Besitzer/Glossar"

    def _lineage():
        # Ein Ziel kann mehrere Upstreams haben -- die muessen in EINEM
        # Aspekt stehen, sonst ueberschreibt der zweite Schreibvorgang den
        # ersten (v3-Semantik: gleiche URN + gleicher Aspekt = ersetzen).
        by_down: dict[str, list[str]] = {}
        for e in plan.edges:
            if e.declared:
                by_down.setdefault(e.downstream, []).append(e.upstream)
        records = [
            {"urn": down, "upstreamLineage": {"value": {"upstreams": [
                {"dataset": up, "type": "TRANSFORMED", "auditStamp": STAMP}
                for up in sorted(set(ups))]}}}
            for down, ups in by_down.items()]
        for group in _chunks(records, batch):
            gms.upsert("dataset", group)
        return f"{len(records)} Ziele, {sum(len(v) for v in by_down.values())} Kanten"

    def _queries():
        for group in _chunks(plan.queries, batch):
            gms.upsert("query", [
                {"urn": q["urn"],
                 "queryProperties": {"value": {
                     "statement": {"value": q["sql"], "language": "SQL"},
                     "source": "MANUAL", "created": STAMP, "lastModified": STAMP}},
                 "querySubjects": {"value": {"subjects": [
                     {"entity": s} for s in q["subjects"]]}}}
                for q in group])
        return f"{len(plan.queries)} Query-Entitaeten"

    def _purge():
        rows = purge_usage(gms, [d.urn for d in plan.datasets if d.usage])
        return f"{rows} Alt-Zeilen entfernt"

    def _usage():
        mcps = []
        for d in plan.datasets:
            for ts_ms, total, unique in d.usage:
                mcps.append(MetadataChangeProposalWrapper(
                    entityUrn=d.urn,
                    aspect=DatasetUsageStatisticsClass(
                        timestampMillis=ts_ms,
                        eventGranularity=TimeWindowSizeClass(unit="DAY", multiple=1),
                        uniqueUserCount=unique, totalSqlQueries=total)))
        # Gebuendelt statt einzeln: 18 ms/Bucket gemessen gegen 71 ms
        # (07.08., 20 Buckets je Variante gegen 28080).
        #
        # `EmitMode.SYNC_PRIMARY` ist NICHT Geschmack, sondern ein
        # gemessener Fehlbefund: `emit_mcps` ohne Modus laeuft in der
        # Vorgabe ASYNCHRON ueber Kafka. Der Smoke-Lauf (Skala smoke, 87
        # Buckets) meldete deshalb HTTP-seitig Erfolg, und die Rueckluse
        # aus der Rohablage fand unmittelbar danach **0 von 87** Zeilen --
        # exakt die Form von Falle 21 (quittiert, nicht geschrieben), nur
        # diesmal selbst verursacht. SYNC_PRIMARY schreibt in den
        # Primaerspeicher, BEVOR der Aufruf zurueckkehrt; genau aus dem
        # liest `verify_plan`. Ein Modus, bei dem 'geschrieben' und
        # 'nachlesbar' auseinanderfallen, ist fuer ein Werkzeug mit der
        # These "wir behaupten nur, was wir gemessen haben" untauglich.
        for group in _chunks(mcps, usage_batch):
            emitter.emit_mcps(list(group), emit_mode=EmitMode.SYNC_PRIMARY)
        return f"{len(mcps)} Nutzungsfenster"

    step("Domaenen", _domains)
    step("Glossarbegriffe", _terms)
    step("Tabellen (datasetProperties)", _datasets)
    step("Governance (domain/owner/glossary)", _governance)
    step("Deklarierte Kanten (upstreamLineage)", _lineage)
    step("Query-Entitaeten", _queries)
    step("Nutzungs-Historie gewiped", _purge)
    step("Nutzungsfenster (SDK-Emitter, gebuendelt)", _usage)
    return steps


# --- Rueckluse ------------------------------------------------------------


def verify_plan(gms: Gms, plan: Plan, verbose: bool = True) -> dict:
    """Jeder Schreibvorgang wird zurueckgelesen. Fehlt etwas, ist der Lauf
    GESCHEITERT -- kein stilles Weiterlaufen (Falle 21: HTTP 200 ohne
    Wirkung ist auf dieser Instanz belegt).

    Gelesen wird aus dem PRIMAERSPEICHER (`get_aspect`, Rohablage), nicht
    aus Such-/Graph-Index oder GraphQL-Aggregation -- die hinken nach
    (Fallen 15/19) und wuerden ein 'fehlt' melden, wo nur der Index noch
    nicht nachgezogen ist.
    """
    out: dict[str, Any] = {}
    missing_props: list[str] = []
    for d in plan.datasets:
        a = gms.get_aspect("dataset", d.urn, "datasetProperties")
        if not a or (a.get("value") or {}).get("description") != d.description:
            missing_props.append(d.urn)
    out["datasets_expected"] = len(plan.datasets)
    out["datasets_read_back"] = len(plan.datasets) - len(missing_props)
    out["datasets_missing"] = missing_props[:10]

    by_down: dict[str, set[str]] = {}
    for e in plan.edges:
        if e.declared:
            by_down.setdefault(e.downstream, set()).add(e.upstream)
    bad_lineage: list[str] = []
    for down, ups in by_down.items():
        a = gms.get_aspect("dataset", down, "upstreamLineage")
        got = {u.get("dataset") for u in ((a or {}).get("value") or {}).get("upstreams", [])}
        if not ups <= got:
            bad_lineage.append(down)
    out["lineage_targets_expected"] = len(by_down)
    out["lineage_targets_read_back"] = len(by_down) - len(bad_lineage)
    out["lineage_missing"] = bad_lineage[:10]

    bad_q: list[str] = []
    for q in plan.queries:
        a = gms.get_aspect("query", q["urn"], "querysubjects")
        got = {s.get("entity") for s in ((a or {}).get("value") or {}).get("subjects", [])}
        if set(q["subjects"]) != got:
            bad_q.append(q["urn"])
    out["queries_expected"] = len(plan.queries)
    out["queries_read_back"] = len(plan.queries) - len(bad_q)
    out["queries_missing"] = bad_q[:10]

    # Zeitreihen mit Nachfassen: `EmitMode.SYNC_PRIMARY` schreibt vor der
    # Rueckkehr in den Primaerspeicher, aber ein einzelner zu frueher Blick
    # ist auch keine Abwesenheit (`verification.md`). Deshalb bis zu drei
    # Anlaeufe NUR auf die Nachzuegler -- und danach ein lautes Nein, kein
    # Achselzucken.
    want_usage = {d.urn: len(d.usage) for d in plan.datasets if d.usage}
    counts: dict[str, int] = {}
    pending = set(want_usage)
    for attempt in range(3):
        for urn in sorted(pending):
            counts[urn] = len(_raw_usage_rows(gms, urn))
        pending = {u for u in want_usage if counts.get(u, 0) != want_usage[u]}
        if not pending:
            break
        if verbose:
            print(f"  Nutzungsfenster: {len(pending)} Tabellen unvollstaendig "
                  f"(Versuch {attempt + 1}/3) -- warte 10s")
        time.sleep(10)
    bad_usage = [f"{u} ({counts.get(u, 0)} statt {want_usage[u]})" for u in sorted(pending)]
    out["usage_buckets_expected"] = sum(want_usage.values())
    out["usage_buckets_read_back"] = sum(counts.values())
    out["usage_missing"] = bad_usage[:10]

    out["all_read_back"] = not (missing_props or bad_lineage or bad_q or bad_usage)
    if verbose:
        print(f"  Tabellen        {out['datasets_read_back']}/{out['datasets_expected']}")
        print(f"  Kanten-Ziele    {out['lineage_targets_read_back']}/{out['lineage_targets_expected']}")
        print(f"  Query-Entitaeten{out['queries_read_back']:>4}/{out['queries_expected']}")
        print(f"  Nutzungsfenster {out['usage_buckets_read_back']}/{out['usage_buckets_expected']}")
    return out


_GRAPH_LINEAGE_Q = """
query($urn: String!) {
  dataset(urn: $urn) {
    lineage(input: {direction: DOWNSTREAM, start: 0, count: 200}) {
      relationships { entity { urn } }
    }
  }
}
"""


def wait_for_graph_index(gms: Gms, plan: Plan, sample: int = 40,
                         timeout_s: float = 420.0, verbose: bool = True) -> dict:
    """Der Ledger liest deklarierte Kanten ueber den GRAPH-Index
    (`fetch_declared_edges` -> GraphQL `lineage`), nicht ueber den
    Primaerspeicher. Der Index wird per Kafka-MCL nachgezogen und hinkt
    (Falle 15). Ein Lauf, der zu frueh startet, misst `unknown`, wo
    `confirmed` steht -- deshalb wird gewartet und GEMESSEN, wie lange.

    Geprueft wird eine Stichprobe von Fokussen; die Ungeduld hat ein
    Zeitlimit, und ein Nicht-Erreichen ist ein FEHLER, kein Achselzucken.
    """
    focus_edges: dict[str, set[str]] = {}
    for e in plan.edges:
        if e.declared:
            focus_edges.setdefault(e.upstream, set()).add(e.downstream)
    keys = sorted(focus_edges)
    rng = random.Random(4711)
    probe = keys if len(keys) <= sample else rng.sample(keys, sample)

    t0 = time.perf_counter()
    while True:
        missing = 0
        for f in probe:
            data = gms.graphql(_GRAPH_LINEAGE_Q, {"urn": f})
            rels = ((data.get("dataset") or {}).get("lineage") or {}).get("relationships") or []
            got = {r["entity"]["urn"] for r in rels if r.get("entity")}
            if not focus_edges[f] <= got:
                missing += 1
        waited = time.perf_counter() - t0
        if missing == 0:
            if verbose:
                print(f"  Graph-Index vollstaendig fuer {len(probe)} Fokusse "
                      f"nach {waited:.1f}s")
            return {"graph_index_sample": len(probe), "graph_index_seconds": round(waited, 1),
                    "graph_index_complete": True}
        if waited > timeout_s:
            return {"graph_index_sample": len(probe), "graph_index_seconds": round(waited, 1),
                    "graph_index_complete": False,
                    "graph_index_focuses_incomplete": missing}
        if verbose:
            print(f"  Graph-Index: {missing}/{len(probe)} Fokusse noch unvollstaendig "
                  f"({waited:.0f}s) -- warte")
        time.sleep(15)


# --- Aufraeumen -----------------------------------------------------------


def cleanup_plan(gms: Gms, plan: Plan, verbose: bool = True) -> dict:
    """Alles wieder weg -- und die Loeschung zurueckgelesen.

    "Jeder Live-Lauf raeumt hinter sich auf. Probe-Entitaeten loeschen und
    die Loeschung zurueeklesen" (`UEBERGABE.md` §7.2). Gebraucht wird das
    vor allem beim Wechsel der Skala: eine Vormessung auf `--scale smoke`
    legt ANDERE Tabellen an als der volle Lauf (andere Namen aus demselben
    Vokabular), die sonst als Waisen im Katalog stehen blieben und die
    Zaehlung des Demo-Katalogs verfaelschten.

    Route: `POST /entities?action=delete` mit `{"urn": ...}`. Live geprueft
    (07.08. gegen 28080): danach meldet GraphQL `entityExists: false` --
    im Gegensatz zum blossen Loeschen einzelner Aspekte, das die Entitaet
    im Suchindex stehen laesst. Die Zeitreihe wird VORHER separat gewiped,
    weil sie an einer eigenen Route haengt.
    """
    urns = [d.urn for d in plan.datasets]
    rows = purge_usage(gms, [d.urn for d in plan.datasets if d.usage])
    for urn in urns + [q["urn"] for q in plan.queries]:
        _validate_urn(urn)
        status, body = gms._send("POST", f"{gms.base}/entities?action=delete", {"urn": urn})
        if status != 200:
            raise GmsError(f"delete {urn} HTTP {status}: {str(body)[:200]}")

    exists_q = "query($urn: String!) { entityExists(urn: $urn) }"
    leftover = []
    for urn in urns + [q["urn"] for q in plan.queries]:
        if gms.graphql(exists_q, {"urn": urn}).get("entityExists"):
            leftover.append(urn)
    out = {"cleanup_entities": len(urns) + len(plan.queries),
           "cleanup_usage_rows_removed": rows,
           "cleanup_leftover": len(leftover),
           "cleanup_leftover_sample": leftover[:10],
           "cleanup_verified": not leftover}
    if verbose:
        print(f"  geloescht: {out['cleanup_entities']} Entitaeten, "
              f"{rows} Nutzungszeilen -- Reste: {len(leftover)}")
    return out


# --- Manifest -------------------------------------------------------------


def write_manifest(plan: Plan, summary: dict, path: Path = MANIFEST_PATH) -> None:
    manifest = {
        "seeded": True,
        "seeded_statement": SEEDED_STATEMENT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gms_url": GMS_DEFAULT,
        "namespace_prefix": NAMESPACE_PREFIX,
        "naming_note": (
            "Kein Tabellenname und keine Query-ID nennt den erwarteten "
            "Kanten-Zustand -- 'expected_state' unten ist die Erwartung dieses "
            "Labors und wird in der Oberflaeche nirgends angezeigt. Sie "
            "existiert, damit der echte Lauf dagegen gehalten werden kann. "
            "Der Datenbank-Praefix 'probate_demo_' ist die Offenlegung, kein "
            "Urteil: er steht auf jeder Zeile gleich."
        ),
        "focus_note": (
            "Fokusse sind ausschliesslich die Ebenen 'raw' und 'core', "
            "Paar-Query-Partner ausschliesslich 'staging' und 'marts'. Grund: "
            "die Query-Ko-Okkurrenz ist ungerichtet -- waere ein Partner "
            "selbst Fokus, entstuende zu jeder bestaetigten Kante eine "
            "gespiegelte 'missing'-Kante, die niemand gemeint hat."
        ),
        "summary": summary,
        "focuses": sorted(plan.focuses),
        "edges": [
            {"upstream_urn": e.upstream, "downstream_urn": e.downstream,
             "declared_lineage": e.declared, "pair_query": e.pair_query,
             "expected_state": e.expected_state}
            for e in plan.edges
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


# --- CLI ------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gms-url", default=GMS_DEFAULT)
    p.add_argument("--token", default=None)
    p.add_argument("--scale", default="full", choices=sorted(SCALES))
    p.add_argument("--seed", type=int, default=20260807)
    p.add_argument("--batch", type=int, default=200)
    p.add_argument("--usage-batch", type=int, default=400)
    p.add_argument("--plan-only", action="store_true",
                   help="nur planen und die Verteilung drucken, nichts schreiben")
    p.add_argument("--cleanup", action="store_true",
                   help="den Katalog dieser Skala wieder loeschen statt ihn anzulegen")
    p.add_argument("--manifest", default=str(MANIFEST_PATH))
    p.add_argument("--out", default="harness/runs/demo-katalog-seed.json")
    args = p.parse_args(argv)

    if args.gms_url not in (GMS_DEFAULT, "http://127.0.0.1:28080"):
        print(f"VERWEIGERT: nur {GMS_DEFAULT} ist erlaubt (global-constraints).",
              file=sys.stderr)
        return 2

    plan = build_plan(SCALES[args.scale], seed=args.seed)
    summary = plan_summary(plan)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if args.plan_only:
        return 0

    token = args.token if args.token is not None else os.environ.get("DATAHUB_TOKEN")
    gms = Gms(base_url=args.gms_url, token=token)
    emitter = DatahubRestEmitter(gms_server=args.gms_url, token=token)

    if args.cleanup:
        print(f"\n  Loesche Skala {args.scale} von {args.gms_url}\n")
        clean = cleanup_plan(gms, plan)
        print(json.dumps(clean, indent=2, ensure_ascii=False))
        return 0 if clean["cleanup_verified"] else 1

    print(f"\n  Schreibe gegen {args.gms_url}, Skala {args.scale}\n")
    t0 = time.perf_counter()
    steps = write_plan(gms, emitter, plan, batch=args.batch,
                       usage_batch=args.usage_batch)
    write_seconds = round(time.perf_counter() - t0, 2)

    print("\n  Warte auf den Graph-Index (Falle 15) ...")
    index = wait_for_graph_index(gms, plan)

    print("\n  Rueckluse (Primaerspeicher):")
    verify = verify_plan(gms, plan)

    write_manifest(plan, summary, Path(args.manifest))

    artifact = {
        "seeded": True,
        "seeded_statement": SEEDED_STATEMENT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gms_url": args.gms_url,
        "scale": args.scale,
        "plan_seed": args.seed,
        "demo_catalog_datasets": summary["datasets"],
        "demo_catalog_edges_planned": summary["edges"],
        "demo_catalog_queries": summary["queries"],
        "demo_catalog_focuses": summary["focuses"],
        "demo_catalog_usage_buckets": summary["usage_buckets"],
        "demo_catalog_platforms": len(summary["platforms"]),
        "demo_catalog_databases": len(summary["databases"]),
        "demo_catalog_seed_seconds": write_seconds,
        "demo_catalog_readback_complete": verify["all_read_back"],
        "summary": summary,
        "steps": [{"what": s.what, "seconds": s.seconds, "detail": s.detail}
                  for s in steps],
        "graph_index": index,
        "verify": verify,
        "manifest": str(Path(args.manifest)).replace("\\", "/"),
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")

    print(f"\n  Schreiben gesamt: {write_seconds}s   Artefakt: {out_path}")
    print(f"  Manifest: {args.manifest}")
    if not verify["all_read_back"]:
        print("\n  FEHLER: nicht alles zurueckgelesen -- der Lauf gilt als gescheitert.")
        return 1
    if not index.get("graph_index_complete"):
        print("\n  FEHLER: Graph-Index nicht vollstaendig -- der Ledger-Lauf "
              "wuerde Kanten uebersehen.")
        return 1
    print("  Alles zurueckgelesen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
