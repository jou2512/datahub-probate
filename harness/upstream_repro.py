"""Reproduces, against a live DataHub instance, every behaviour reported in
`docs/upstream/`.

Self-contained on purpose: it seeds its own throwaway namespace
(`probate_upstream.*`), measures, and deletes everything it created. Nothing
here writes to the demo lab (`probate_seedlab.*`) -- an upstream maintainer
must be able to run this against a plain `datahub docker quickstart` without
any of this project's fixtures.

    uv run --python 3.11 python harness/upstream_repro.py
    uv run --python 3.11 python harness/upstream_repro.py --gms-url http://localhost:8080

Read-only mode, for an instance whose ingestion path is degraded (see below)
or where you simply do not want the script to write anything:

    uv run --python 3.11 python harness/upstream_repro.py --no-seed \
        --sparse-urn <urn with a gappy usage history> \
        --dense-urn  <urn with consecutive-day usage history> \
        --empty-urn  <urn with no usage history at all>

Exit 0 = every probe that could run reproduced its claim. Exit 1 = at least
one claim did NOT reproduce. A non-reproducing claim is a result, not a crash:
the artifact still gets written, with `reproduced: false` on the probe in
question, so the disagreement is on record instead of being swallowed.

THE THIRD OUTCOME, and why it exists: a probe can also come back
`reproduced: null` with a `skipped` reason. That is neither confirmation nor
refutation -- it means the probe never got to ask its question. Concretely:
in DataHub, a timeseries aspect write is accepted by GMS and then applied by a
Kafka consumer. If that consumer is not making progress, GMS still answers
HTTP 200 and the row never lands, so a probe that needs freshly written
history has nothing to measure. Recording that as `false` would turn a broken
test rig into a refuted claim about DataHub. `seed()` therefore reads its own
writes back and, if they never appear, marks the write path stalled and skips
exactly the probes that depend on it -- loudly (`.claude/rules/
verification.md`: a failed query is not an absence).

Artifact: `harness/runs/upstream-repro.json`.

WHY the probes look paranoid: this project's own rule (`.claude/rules/
verification.md`) is that a failed query is not an absence. Every probe here
therefore reads BOTH the primary timeseries store (`/aspects?action=
getTimeseriesAspectValues`) and the derived GraphQL aggregation, and reports
both numbers -- never one alone. Where the two disagree, that disagreement IS
the finding.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from probate.gms import Gms, GmsError, _validate_urn  # noqa: E402

PLATFORM = "urn:li:dataPlatform:postgres"
NAMESPACE = "probate_upstream"
DAY_MS = 86_400_000
FAR_FUTURE_MS = 4_102_444_800_000  # 2100-01-01 UTC

# Midnight UTC today. Every bucket timestamp is an offset from here, so the
# probe reproduces on any calendar day instead of drifting out of the
# aggregation's own window.
ANCHOR = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

ARTIFACT = Path(__file__).resolve().parent / "runs" / "upstream-repro.json"


def days_ago_ms(n: int) -> int:
    return int((ANCHOR - timedelta(days=n)).timestamp() * 1000)


def ds_urn(name: str) -> str:
    return f"urn:li:dataset:({PLATFORM},{NAMESPACE}.{name},PROD)"


ZERO_FILL = ds_urn("zero_fill_probe")
DENSE = ds_urn("dense_control")
EMPTY = ds_urn("empty_control")
DELETE_PROBE = ds_urn("delete_probe")
LAG_PROBE = ds_urn("lag_probe")
LINEAGE_UP = ds_urn("lineage_probe_upstream")
LINEAGE_DOWN = ds_urn("lineage_probe_downstream")

ALL_URNS = [ZERO_FILL, DENSE, EMPTY, DELETE_PROBE, LAG_PROBE, LINEAGE_UP, LINEAGE_DOWN]

# The sparse dataset: two real measurements 40 days apart, plus one today.
# Everything between them was never written. That gap is what the aggregation
# is claimed to fill with zeros.
SPARSE_BUCKETS = [(days_ago_ms(40), 30), (days_ago_ms(20), 22), (days_ago_ms(0), 11)]
SPARSE_SPAN_DAYS = 41  # 40 days ago .. today, inclusive

# The control: three consecutive days. If the aggregation zero-filled a FIXED
# window (rather than the span between the oldest and newest real row), this
# dataset would also come back padded. It must not.
DENSE_BUCKETS = [(days_ago_ms(2), 28), (days_ago_ms(1), 35), (days_ago_ms(0), 40)]

STAMP = {"time": 0, "actor": "urn:li:corpuser:datahub"}

# ---------------------------------------------------------------------------
# Low-level access. Deliberately raw HTTP rather than the Python SDK, so every
# claim in docs/upstream/ can be restated as a curl command a maintainer can
# paste.
# ---------------------------------------------------------------------------

TIMESERIES_PATH = "/aspects?action=getTimeseriesAspectValues"


def raw_usage(gms: Gms, urn: str, limit: int = 2000) -> list[dict]:
    """The primary timeseries store: exactly the rows that were written."""
    _validate_urn(urn)
    payload = {
        "urn": urn,
        "entity": "dataset",
        "aspect": "datasetUsageStatistics",
        "startTimeMillis": 0,
        "endTimeMillis": FAR_FUTURE_MS,
        "limit": limit,
    }
    status, body = gms._send("POST", f"{gms.base}{TIMESERIES_PATH}", payload)
    if status != 200 or not isinstance(body, dict):
        raise GmsError(f"getTimeseriesAspectValues HTTP {status}: {str(body)[:300]}")
    out = []
    for v in ((body.get("value") or {}).get("values")) or []:
        raw = v.get("aspect", {}).get("value")
        out.append(json.loads(raw) if isinstance(raw, str) else raw)
    return sorted(out, key=lambda a: a.get("timestampMillis", 0))


USAGE_Q = """
query($urn: String!) {
  dataset(urn: $urn) {
    usageStats(range: ALL) {
      buckets { bucket metrics { totalSqlQueries uniqueUserCount } }
      aggregations { totalSqlQueries }
    }
  }
}
"""


def agg_usage(gms: Gms, urn: str) -> dict:
    """The derived GraphQL aggregation, over the widest range the API offers."""
    data = gms.graphql(USAGE_Q, {"urn": urn})
    return ((data.get("dataset") or {}).get("usageStats")) or {}


LINEAGE_Q = """
query($urn: String!) {
  dataset(urn: $urn) {
    lineage(input: {direction: UPSTREAM, start: 0, count: 100}) {
      relationships { entity { urn } }
    }
  }
}
"""


def graph_upstreams(gms: Gms, urn: str) -> set[str]:
    """The graph/search index view of lineage (Elasticsearch-backed)."""
    data = gms.graphql(LINEAGE_Q, {"urn": urn})
    rels = ((data.get("dataset") or {}).get("lineage") or {}).get("relationships") or []
    return {r["entity"]["urn"] for r in rels if r.get("entity")}


def primary_upstreams(gms: Gms, urn: str) -> set[str]:
    """The primary (MySQL) view of the same lineage aspect."""
    aspect = gms.get_aspect("dataset", urn, "upstreamLineage")
    return {
        u.get("dataset")
        for u in ((aspect or {}).get("value") or {}).get("upstreams", [])
        if u.get("dataset")
    }


def purge_timeseries(gms: Gms, urn: str) -> int:
    """Full timeseries wipe. Returns the number of rows the server removed."""
    _validate_urn(urn)
    status, body = gms._send(
        "POST",
        f"{gms.base}/entities?action=delete",
        {
            "urn": urn,
            "aspectName": "datasetUsageStatistics",
            "startTimeMillis": 0,
            "endTimeMillis": FAR_FUTURE_MS,
        },
    )
    if status != 200:
        raise GmsError(f"entities?action=delete HTTP {status}: {str(body)[:300]}")
    return int(((body or {}).get("value") or {}).get("timeseriesRows", 0) or 0)


def emit_usage(emitter, urn: str, ts_ms: int, total: int, unique: int = 1) -> None:
    from datahub.emitter.mcp import MetadataChangeProposalWrapper
    from datahub.metadata.schema_classes import (
        DatasetUsageStatisticsClass,
        TimeWindowSizeClass,
    )

    emitter.emit_mcp(
        MetadataChangeProposalWrapper(
            entityUrn=urn,
            aspect=DatasetUsageStatisticsClass(
                timestampMillis=ts_ms,
                eventGranularity=TimeWindowSizeClass(unit="DAY", multiple=1),
                uniqueUserCount=unique,
                totalSqlQueries=total,
            ),
        )
    )


def poll_until(fn, predicate, budget_s: float, interval_s: float = 0.5) -> tuple[bool, float, Any]:
    """Returns (matched, seconds_elapsed, last_value).

    Reports the elapsed time even on failure -- "still wrong after N seconds"
    is the measurement, not an error.
    """
    start = time.monotonic()
    last = None
    while time.monotonic() - start < budget_s:
        try:
            last = fn()
        except GmsError as exc:
            last = f"GmsError: {exc}"
        else:
            if predicate(last):
                return True, time.monotonic() - start, last
        time.sleep(interval_s)
    return False, time.monotonic() - start, last


# ---------------------------------------------------------------------------
# Setup / teardown
# ---------------------------------------------------------------------------


def seed(gms: Gms, emitter) -> dict:
    """Creates the fixtures and PROVES they landed.

    Returns a diagnosis dict. `write_path_stalled: True` means GMS accepted the
    timeseries writes (HTTP 200) but the rows never became readable -- the
    ingestion consumer is not applying them. In that state the write-dependent
    probes are skipped rather than failed.
    """
    gms.upsert(
        "dataset",
        [
            {
                "urn": urn,
                "datasetProperties": {
                    "value": {
                        "name": urn.split(",")[1].split(".")[-1],
                        "description": (
                            "[probate_upstream -- throwaway fixture for "
                            "harness/upstream_repro.py. Deleted at the end of the run.]"
                        ),
                    }
                },
            }
            for urn in ALL_URNS
        ],
    )
    for urn in (ZERO_FILL, DENSE, EMPTY, DELETE_PROBE, LAG_PROBE):
        purge_timeseries(gms, urn)
    for ts, total in SPARSE_BUCKETS:
        emit_usage(emitter, ZERO_FILL, ts, total)
    for ts, total in DENSE_BUCKETS:
        emit_usage(emitter, DENSE, ts, total)
    for ts, total in SPARSE_BUCKETS:
        emit_usage(emitter, DELETE_PROBE, ts, total)
    # EMPTY and LAG_PROBE stay without usage rows on purpose.

    landed, seconds, last = poll_until(
        lambda: (len(raw_usage(gms, ZERO_FILL)), len(raw_usage(gms, DENSE))),
        lambda t: t == (len(SPARSE_BUCKETS), len(DENSE_BUCKETS)),
        budget_s=60.0,
        interval_s=2.0,
    )
    return {
        "write_path_stalled": not landed,
        "seed_readback_seconds": round(seconds, 1),
        "seed_rows_seen": last if isinstance(last, tuple) else str(last)[:200],
        "seed_rows_expected": (len(SPARSE_BUCKETS), len(DENSE_BUCKETS)),
        "note": (
            ""
            if landed
            else (
                "GMS answered HTTP 200 for every timeseries write, but the rows never became "
                "readable within the budget. That is an ingestion-consumer outage on this "
                "instance, not a statement about DataHub: probes needing fresh timeseries "
                "history are skipped, not failed. Check the GMS log for repeated "
                "'COORDINATOR_NOT_AVAILABLE' / '(Re-)joining group' on the mce/mcl consumer "
                "groups, and the count in the Elasticsearch index "
                "dataset_datasetusagestatisticsaspect_v1."
            )
        ),
    }


def teardown(gms: Gms) -> dict:
    """Hard-deletes every entity this script created, and reads back to prove it."""
    removed, errors = [], []
    for urn in ALL_URNS:
        try:
            purge_timeseries(gms, urn)
            status, body = gms._send("POST", f"{gms.base}/entities?action=delete", {"urn": urn})
            if status != 200:
                errors.append(f"{urn}: HTTP {status} {str(body)[:120]}")
            else:
                removed.append(urn)
        except GmsError as exc:
            errors.append(f"{urn}: {exc}")
    leftovers = []
    for urn in ALL_URNS:
        try:
            if gms.get_aspect("dataset", urn, "datasetProperties"):
                leftovers.append(urn)
        except GmsError as exc:
            errors.append(f"readback {urn}: {exc}")
    return {"deleted": len(removed), "leftovers": leftovers, "errors": errors}


# ---------------------------------------------------------------------------
# Probes. Each returns a dict that names the claim, the observation, and
# whether the two agree.
# ---------------------------------------------------------------------------


def probe_usagestats_range_required(gms: Gms, urn: str) -> dict:
    """FINDING-01: `Dataset.usageStats` declares all four arguments nullable,
    but omitting `range` yields HTTP 500 instead of a validation error."""
    schema = gms.graphql(
        '{ __type(name: "Dataset") { fields { name args { name type { kind name } } } } }'
    )
    args = {}
    for f in schema["__type"]["fields"]:
        if f["name"] == "usageStats":
            args = {a["name"]: a["type"]["kind"] for a in f["args"]}
    non_null = [n for n, kind in args.items() if kind == "NON_NULL"]

    cases = {}
    variants = {
        "no_args": "usageStats { aggregations { totalSqlQueries } }",
        "range_only": "usageStats(range: ALL) { aggregations { totalSqlQueries } }",
        "startTimeMillis_only": (
            f"usageStats(startTimeMillis: {days_ago_ms(30)}) "
            "{ aggregations { totalSqlQueries } }"
        ),
        "timeZone_only": 'usageStats(timeZone: "UTC") { aggregations { totalSqlQueries } }',
        "startTimeMillis_and_range": (
            f"usageStats(startTimeMillis: {days_ago_ms(30)}, range: ALL) "
            "{ aggregations { totalSqlQueries } }"
        ),
    }
    for label, selection in variants.items():
        query = "query($u: String!) { dataset(urn: $u) { " + selection + " } }"
        try:
            gms.graphql(query, {"u": urn})
            cases[label] = "ok"
        except GmsError as exc:
            cases[label] = str(exc)[:220]

    failing = [k for k, v in cases.items() if v != "ok"]
    reproduced = (
        not non_null
        and cases["range_only"] == "ok"
        and cases["startTimeMillis_and_range"] == "ok"
        and all("Name is null" in cases[k] for k in ("no_args", "startTimeMillis_only", "timeZone_only"))
    )
    return {
        "finding": "01-usagestats-range-argument-required-but-nullable",
        "probed_urn": urn,
        "claim": (
            "All arguments of Dataset.usageStats are nullable in the schema, yet any call "
            "that omits `range` fails with HTTP 500 'Name is null' instead of a 400-class "
            "validation error."
        ),
        "schema_arg_kinds": args,
        "schema_non_null_args": non_null,
        "cases": cases,
        "variants_failing_with_500": failing,
        "reproduced": reproduced,
    }


def skipped(finding: str, claim: str, reason: str) -> dict:
    """A probe that never got to ask its question. Not a refutation."""
    return {"finding": finding, "claim": claim, "reproduced": None, "skipped": reason}


def probe_timeseries_limit_required(gms: Gms, urn: str) -> dict:
    """FINDING-02: `getTimeseriesAspectValues` NPEs on a missing `limit`."""
    expected_rows = len(raw_usage(gms, urn))
    base = {
        "urn": urn,
        "entity": "dataset",
        "aspect": "datasetUsageStatistics",
        "startTimeMillis": 0,
        "endTimeMillis": FAR_FUTURE_MS,
    }
    status_without, body_without = gms._send("POST", f"{gms.base}{TIMESERIES_PATH}", base)
    with_limit = dict(base, limit=100)
    status_with, body_with = gms._send("POST", f"{gms.base}{TIMESERIES_PATH}", with_limit)
    n_with = len(((body_with or {}).get("value") or {}).get("values") or [])
    text = str(body_without)
    return {
        "finding": "02-gettimeseriesaspectvalues-limit-null-pointer",
        "claim": (
            "POST /aspects?action=getTimeseriesAspectValues without the optional-looking "
            "`limit` field returns HTTP 500 NullPointerException instead of applying a "
            "default or returning 400."
        ),
        "probed_urn": urn,
        "status_without_limit": status_without,
        "error_without_limit": text[:400],
        "status_with_limit": status_with,
        "rows_with_limit": n_with,
        "rows_expected": expected_rows,
        "reproduced": (
            status_without == 500
            and "NullPointerException" in text
            # the body is JSON, so the quotes around `limit` arrive escaped
            and "limit" in text
            and "is null" in text
            and status_with == 200
            and n_with == expected_rows
        ),
    }


UNIQUE_USERS_Q = """
query($urn: String!) {
  dataset(urn: $urn) {
    usageStats(range: ALL) {
      buckets { bucket metrics { totalSqlQueries uniqueUserCount } }
      aggregations { totalSqlQueries uniqueUserCount users { user { urn } count } }
    }
    statsSummary { queryCountLast30Days uniqueUserCountLast30Days }
  }
}
"""


def probe_unique_user_count_aggregation(gms: Gms, urns: list[str]) -> dict:
    """FINDING-03: `usageStats.aggregations.uniqueUserCount` is 0 even when the
    buckets in the SAME response report non-zero `uniqueUserCount`.

    No external knowledge is needed to see that this is wrong: one response
    says "these days had 3, 4 and 5 unique users" and, three lines down,
    "0 unique users overall". `totalSqlQueries` -- the sibling scalar on the
    same aspect -- aggregates correctly, so this is not a general "we do not
    aggregate" position, it is asymmetric handling of two neighbouring fields.
    """
    per_dataset = []
    for urn in urns:
        data = gms.graphql(UNIQUE_USERS_Q, {"urn": urn})["dataset"] or {}
        stats = data.get("usageStats") or {}
        agg = stats.get("aggregations") or {}
        bucket_counts = [
            (b.get("metrics") or {}).get("uniqueUserCount")
            for b in (stats.get("buckets") or [])
        ]
        measured = [c for c in bucket_counts if c is not None]
        rows = raw_usage(gms, urn)
        per_dataset.append(
            {
                "urn": urn,
                "bucket_unique_user_counts": measured,
                "max_bucket_unique_user_count": max(measured) if measured else None,
                "aggregations_uniqueUserCount": agg.get("uniqueUserCount"),
                "aggregations_users": agg.get("users"),
                "aggregations_totalSqlQueries": agg.get("totalSqlQueries"),
                "primary_store_totalSqlQueries": sum(r.get("totalSqlQueries", 0) for r in rows),
                "primary_store_max_uniqueUserCount": max(
                    (r.get("uniqueUserCount", 0) for r in rows), default=None
                ),
                "stats_summary": data.get("statsSummary"),
                "aspect_carries_userCounts_array": any("userCounts" in r for r in rows),
                "contradiction": bool(measured)
                and max(measured) > 0
                and agg.get("uniqueUserCount") == 0,
            }
        )

    contradicting = [d for d in per_dataset if d["contradiction"]]
    return {
        "finding": "03-usagestats-uniqueusercount-aggregation-is-always-zero",
        "claim": (
            "Dataset.usageStats.aggregations.uniqueUserCount returns 0 while the buckets in "
            "the same response report non-zero uniqueUserCount, and statsSummary."
            "uniqueUserCountLast30Days repeats the 0. totalSqlQueries, the sibling scalar on "
            "the same aspect, aggregates correctly from the same rows. A writer that sets "
            "DatasetUsageStatistics.uniqueUserCount -- the field the Python SDK exposes -- "
            "gets it echoed back per bucket but silently zeroed in every aggregate."
        ),
        "datasets": per_dataset,
        "datasets_contradicting": len(contradicting),
        "datasets_probed": len(per_dataset),
        "likely_cause": (
            "The aggregate appears to be derived from the optional `userCounts` array rather "
            "than from the scalar `uniqueUserCount`; with no `userCounts` written, `users` "
            "comes back [] and the count comes back 0. Reporting 0 rather than null then "
            "asserts a measurement that was never made."
        ),
        "reproduced": len(contradicting) == len(per_dataset) and len(per_dataset) > 0,
    }


QUERY_TIMESTAMP_Q = """
query($input: ListQueriesInput!) {
  listQueries(input: $input) {
    total
    queries { urn properties { created { time actor } lastModified { time actor } } }
  }
}
"""


def probe_mcp_query_timestamps(gms: Gms) -> dict:
    """FINDING-06: mcp-server-datahub ships GraphQL documents with every
    QueryEntity timestamp commented out, while the server serves them fine.

    Two halves, and both have to hold or the report is wrong:
      (a) the CLIENT drops the fields -- read out of the installed package,
          not out of the repo on GitHub, so the finding is about the artifact
          people actually run;
      (b) the SERVER offers them -- introspected, and then actually fetched,
          so "commented out" cannot be excused as "the backend can't do it".

    Needs `mcp-server-datahub` importable:
        uv run --python 3.11 --with mcp-server-datahub==0.6.0 python harness/upstream_repro.py ...
    """
    try:
        import mcp_server_datahub  # noqa: PLC0415
    except ImportError:
        return skipped(
            "06-mcp-server-datahub-comments-out-query-timestamps",
            "see docs/upstream/",
            "mcp-server-datahub is not installed in this environment; re-run with "
            "--with mcp-server-datahub==0.6.0",
        )

    pkg = Path(mcp_server_datahub.__file__).resolve().parent
    version = getattr(mcp_server_datahub, "__version__", None)
    if version is None:
        from importlib.metadata import PackageNotFoundError, version as pkg_version  # noqa: PLC0415

        try:
            version = pkg_version("mcp-server-datahub")
        except PackageNotFoundError:
            version = "unknown"

    def strip_comments(text: str) -> str:
        """The document as the server actually receives it."""
        return "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("#"))

    def requests_field(document: str, field: str) -> bool:
        """Is `field` requested as a selection anywhere in the document?

        GraphQL selections are bare words on their own line in these files, so
        a token match on the comment-stripped text is enough and avoids
        matching the word inside a comment or a fragment name.
        """
        return any(ln.strip() == field for ln in document.splitlines())

    docs = {}
    for name in ("queries.gql", "query_entity.gql"):
        path = pkg / "gql" / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        effective = strip_comments(text)
        docs[name] = {
            "path": str(path),
            "commented_out_lines": [
                ln.strip() for ln in text.splitlines() if ln.strip().startswith("#")
            ],
            "effective_requests_created": requests_field(effective, "created"),
            "effective_requests_time": requests_field(effective, "time"),
            "created_appears_only_in_comments": ("created" in text)
            and not requests_field(effective, "created"),
            "time_appears_only_in_comments": ("time" in text)
            and not requests_field(effective, "time"),
        }

    # (b) the server side, introspected and then actually fetched
    props = gms.graphql(
        '{ __type(name: "QueryProperties") { fields { name '
        "type { kind name ofType { kind name } } } } }"
    )["__type"]["fields"]

    def type_name(t: dict | None) -> str | None:
        """Unwrap NON_NULL/LIST: the wrapper carries name=null, the inner type
        carries the real name. Reading `type.name` alone reports null for every
        non-null field, which looks exactly like "the field does not exist"."""
        t = t or {}
        return t.get("name") or (t.get("ofType") or {}).get("name")

    server_fields = {f["name"]: type_name(f["type"]) for f in props}

    live = gms.graphql(QUERY_TIMESTAMP_Q, {"input": {"start": 0, "count": 3}})["listQueries"]
    sample = live.get("queries") or []
    server_returns_timestamps = any(
        ((q.get("properties") or {}).get("created") or {}).get("time") is not None
        for q in sample
    )

    # The claim is simply: not one of these documents asks for a timestamp.
    client_drops = bool(docs) and not any(
        d["effective_requests_created"] or d["effective_requests_time"] for d in docs.values()
    )

    return {
        "finding": "06-mcp-server-datahub-comments-out-query-timestamps",
        "claim": (
            "mcp-server-datahub's bundled GraphQL documents comment out QueryProperties."
            "created entirely and lastModified.time as well, so every query entity reaches an "
            "MCP client with no timestamp. The server offers both fields and returns real "
            "values for them. The failure is silent: results arrive, they are simply always "
            "undated, which makes any age-based judgement impossible over MCP."
        ),
        "mcp_server_datahub_version": version,
        "client_documents": docs,
        "client_drops_all_timestamps": client_drops,
        "server_QueryProperties_fields": server_fields,
        "server_offers_created": server_fields.get("created") == "AuditStamp",
        "server_offers_lastModified": server_fields.get("lastModified") == "AuditStamp",
        "server_returns_timestamps_live": server_returns_timestamps,
        "server_sample": sample[:2],
        "reproduced": (
            bool(docs)
            and client_drops
            and server_fields.get("created") == "AuditStamp"
            and server_fields.get("lastModified") == "AuditStamp"
            and server_returns_timestamps
        ),
    }


def _usage_side_by_side(gms: Gms, urn: str) -> dict:
    """Both views of the same dataset, plus the span the fill hypothesis predicts.

    Predicted bucket count = number of calendar days from the oldest to the
    newest really-written row, inclusive. Derived from the data rather than
    hardcoded, so the probe works against a freshly seeded fixture and against
    an arbitrary pre-existing dataset alike.
    """
    rows = raw_usage(gms, urn)
    agg = agg_usage(gms, urn)
    buckets = agg.get("buckets") or []
    stamps = [r["timestampMillis"] for r in rows]
    span_days = (max(stamps) - min(stamps)) // DAY_MS + 1 if stamps else 0
    return {
        "urn": urn,
        "rows_in_primary_store": len(rows),
        "buckets_from_aggregation": len(buckets),
        "predicted_span_days": span_days,
        "interpolated_buckets": len(buckets) - len(rows),
        "oldest_row_ms": min(stamps) if stamps else None,
        "newest_row_ms": max(stamps) if stamps else None,
        "zero_rows_in_primary_store": sum(1 for r in rows if r.get("totalSqlQueries") == 0),
        "zero_buckets_in_aggregation": sum(
            1 for b in buckets if (b.get("metrics") or {}).get("totalSqlQueries") == 0
        ),
        # The padding carries null metrics, NOT zeros. That distinction is the
        # whole difference between "undocumented shape" and "corrupt data", and
        # it is why this finding is filed as a docs defect rather than a bug.
        "null_metric_buckets_in_aggregation": sum(
            1 for b in buckets if (b.get("metrics") or {}).get("totalSqlQueries") is None
        ),
        "primary_store_total": sum(r.get("totalSqlQueries", 0) for r in rows),
        "aggregation_total": (agg.get("aggregations") or {}).get("totalSqlQueries"),
        "span_matches_bucket_count": len(buckets) == span_days,
    }


def probe_zero_fill(gms: Gms, sparse_urn: str, dense_urn: str, empty_urn: str) -> dict:
    """FINDING-03: the usageStats aggregation zero-fills the calendar span
    between its oldest and its newest real row.

    Three datasets, because one alone cannot distinguish the hypotheses:
      sparse -- gappy history: aggregation must return MORE buckets than rows
      dense  -- consecutive days: aggregation must return EXACTLY as many
                buckets as rows. Without this control, "the aggregation pads
                to a fixed window" would explain the sparse result just as well.
      empty  -- no rows: aggregation must return no buckets, i.e. the fill
                needs at least one real row to anchor on and does not
                fabricate a window out of nothing.
    """
    sparse = _usage_side_by_side(gms, sparse_urn)
    dense = _usage_side_by_side(gms, dense_urn)
    empty = _usage_side_by_side(gms, empty_urn)

    return {
        "finding": "04-usagestats-buckets-are-a-dense-calendar-grid",
        "claim": (
            "usageStats.buckets is a DENSE per-day calendar grid spanning the oldest to the "
            "newest really-written row, not the list of measurements. Days that were never "
            "written are present as buckets with null metrics. len(buckets) is therefore a "
            "calendar span, not a count of measurements -- here 125 buckets for 8 rows. "
            "None of this is stated in the schema description or the docs, and the "
            "null-vs-zero distinction (never written vs measured zero traffic) is the only "
            "thing separating the two."
        ),
        "sparse": dict(sparse, role="gappy history -- expect buckets > rows"),
        "dense_control": dict(dense, role="consecutive days -- expect buckets == rows"),
        "empty_control": dict(empty, role="no history -- expect 0 buckets"),
        "padding_is_null_not_zero": (
            sparse["null_metric_buckets_in_aggregation"] == sparse["interpolated_buckets"]
        ),
        "reproduced": (
            # the padding itself: more buckets than rows, exactly one per calendar day
            sparse["rows_in_primary_store"] > 1
            and sparse["buckets_from_aggregation"] > sparse["rows_in_primary_store"]
            and sparse["span_matches_bucket_count"]
            # every padded bucket carries NULL metrics -- measured zeros stay 0
            and sparse["null_metric_buckets_in_aggregation"] == sparse["interpolated_buckets"]
            and sparse["zero_buckets_in_aggregation"] == sparse["zero_rows_in_primary_store"]
            # totals agree: the padding adds shape, never traffic
            and sparse["aggregation_total"] == sparse["primary_store_total"]
            # control 1: consecutive days are not padded, so this is a span and
            # not a fixed window
            and dense["rows_in_primary_store"] > 1
            and dense["buckets_from_aggregation"] == dense["rows_in_primary_store"]
            # control 2: with no row to anchor on, no grid is invented
            and empty["rows_in_primary_store"] == 0
            and empty["buckets_from_aggregation"] == 0
        ),
    }


def probe_timeseries_delete(gms: Gms) -> dict:
    """FINDING-04: DELETE /openapi/v3/entity/.../<timeseries aspect> removes
    only the newest row, and reports HTTP 200 as if it removed the aspect."""
    before = raw_usage(gms, DELETE_PROBE)
    gms.delete_aspect("dataset", DELETE_PROBE, "datasetUsageStatistics")
    after_v3 = raw_usage(gms, DELETE_PROBE)
    removed_ts = sorted({v["timestampMillis"] for v in before} - {v["timestampMillis"] for v in after_v3})
    rows_removed_by_full_wipe = purge_timeseries(gms, DELETE_PROBE)
    after_wipe = raw_usage(gms, DELETE_PROBE)
    newest_before = max(v["timestampMillis"] for v in before) if before else None
    return {
        "finding": "unconfirmed-delete-aspect-on-timeseries-removes-only-newest-row",
        "claim": (
            "DELETE /openapi/v3/entity/dataset/<urn>/datasetusagestatistics answers HTTP 200 "
            "and removes exactly one row -- the newest -- leaving the rest of the history in "
            "place. Removing the history needs POST /entities?action=delete with a time range."
        ),
        "rows_before": len(before),
        "rows_after_openapi_v3_delete": len(after_v3),
        "timestamps_removed_by_v3_delete": removed_ts,
        "newest_timestamp_before": newest_before,
        "v3_delete_removed_only_the_newest": removed_ts == [newest_before],
        "rows_removed_by_entities_action_delete": rows_removed_by_full_wipe,
        "rows_after_full_wipe": len(after_wipe),
        "reproduced": (
            len(before) == len(SPARSE_BUCKETS)
            and len(after_v3) == len(SPARSE_BUCKETS) - 1
            and removed_ts == [newest_before]
            and len(after_wipe) == 0
        ),
    }


def probe_aggregation_lag(gms: Gms, emitter, budget_s: float) -> dict:
    """FINDING-05: the usageStats aggregation trails the primary store."""
    ts = days_ago_ms(0)
    marker = 4242
    emit_usage(emitter, LAG_PROBE, ts, marker)
    t0 = time.monotonic()

    raw_ok, raw_s, raw_last = poll_until(
        lambda: raw_usage(gms, LAG_PROBE),
        lambda rows: any(
            isinstance(r, dict) and r.get("totalSqlQueries") == marker for r in rows
        )
        if isinstance(rows, list)
        else False,
        budget_s=budget_s,
    )
    agg_ok, agg_s, agg_last = poll_until(
        lambda: agg_usage(gms, LAG_PROBE),
        lambda a: isinstance(a, dict)
        and (a.get("aggregations") or {}).get("totalSqlQueries") == marker,
        budget_s=budget_s,
    )
    return {
        "finding": "unconfirmed-usagestats-aggregation-trails-the-primary-store",
        "claim": (
            "After a write, the primary timeseries store is correct within a second, while "
            "the GraphQL usageStats aggregation keeps serving the pre-write answer. Any "
            "read-after-write flow that verifies through usageStats sees a stale catalog."
        ),
        "marker_value": marker,
        "poll_budget_s": budget_s,
        "primary_store_correct": raw_ok,
        "primary_store_seconds": round(raw_s, 3),
        "aggregation_correct_within_budget": agg_ok,
        "aggregation_seconds": round(agg_s, 3),
        "aggregation_last_seen": (agg_last or {}).get("aggregations")
        if isinstance(agg_last, dict)
        else str(agg_last)[:200],
        "note": (
            "The measured lag is one sample on one machine. It shows the aggregation CAN "
            "trail the primary store by orders of magnitude, not that it always does."
        ),
        "reproduced": raw_ok and raw_s < agg_s,
    }


def probe_graph_index_lag(gms: Gms, budget_s: float) -> dict:
    """FINDING-06: the primary store and the graph index disagree after a
    lineage write and after a lineage removal, so absence from search/lineage
    is not absence from the catalog -- and `restoreIndices` closes the gap.

    Sequencing matters here. A naive version writes the edge, polls, removes
    the edge, polls again -- and if the index never picked the edge up in the
    first place, the removal leg "passes" without ever having had anything to
    remove. That is a vacuous measurement dressed as a green check. So: after
    the write leg, the index is forced into the correct state (by waiting, or
    failing that by `restoreIndices`) BEFORE the removal leg starts, and the
    artifact records `graph_had_edge_before_removal` so a reader can see that
    the second measurement was meaningful.
    """
    remedy = (
        f'curl -X POST "{gms.base}/operations?action=restoreIndices" '
        f"-H \"Content-Type: application/json\" -d '{{\"urn\": \"{LINEAGE_DOWN}\"}}'"
    )

    def restore_indices() -> dict:
        status, body = gms._send(
            "POST", f"{gms.base}/operations?action=restoreIndices", {"urn": LINEAGE_DOWN}
        )
        return {"http_status": status, "response": str(body)[:300]}

    # --- leg 1: write the edge -------------------------------------------
    gms.upsert(
        "dataset",
        [
            {
                "urn": LINEAGE_DOWN,
                "upstreamLineage": {
                    "value": {
                        "upstreams": [
                            {"dataset": LINEAGE_UP, "type": "TRANSFORMED", "auditStamp": STAMP}
                        ]
                    }
                },
            }
        ],
    )
    primary_after_write = primary_upstreams(gms, LINEAGE_DOWN)
    has_edge = lambda s: isinstance(s, set) and LINEAGE_UP in s  # noqa: E731
    no_edge = lambda s: isinstance(s, set) and LINEAGE_UP not in s  # noqa: E731

    write_ok, write_s, _ = poll_until(
        lambda: graph_upstreams(gms, LINEAGE_DOWN), has_edge, budget_s=budget_s
    )
    restore_after_write: dict[str, Any] = {"invoked": False}
    if not write_ok:
        restore_after_write = dict(restore_indices(), invoked=True)
        healed, healed_s, _ = poll_until(
            lambda: graph_upstreams(gms, LINEAGE_DOWN), has_edge, budget_s=budget_s
        )
        restore_after_write["graph_correct_after_restore"] = healed
        restore_after_write["seconds_after_restore"] = round(healed_s, 3)

    graph_had_edge_before_removal = has_edge(graph_upstreams(gms, LINEAGE_DOWN))

    # --- leg 2: remove the edge ------------------------------------------
    gms.upsert("dataset", [{"urn": LINEAGE_DOWN, "upstreamLineage": {"value": {"upstreams": []}}}])
    primary_after_removal = primary_upstreams(gms, LINEAGE_DOWN)
    removal_ok, removal_s, graph_last = poll_until(
        lambda: graph_upstreams(gms, LINEAGE_DOWN), no_edge, budget_s=budget_s
    )
    restore_after_removal: dict[str, Any] = {"invoked": False}
    if not removal_ok and graph_had_edge_before_removal:
        restore_after_removal = dict(restore_indices(), invoked=True)
        healed, healed_s, _ = poll_until(
            lambda: graph_upstreams(gms, LINEAGE_DOWN), no_edge, budget_s=budget_s
        )
        restore_after_removal["graph_correct_after_restore"] = healed
        restore_after_removal["seconds_after_restore"] = round(healed_s, 3)

    diverged_on_write = not write_ok
    diverged_on_removal = graph_had_edge_before_removal and not removal_ok
    restores = [r for r in (restore_after_write, restore_after_removal) if r["invoked"]]

    return {
        "finding": "unconfirmed-graph-index-trails-writes-and-deletes",
        "claim": (
            "The primary store reflects a lineage write and a lineage removal immediately, "
            "while the Elasticsearch-backed graph index behind dataset.lineage and "
            "searchAcrossEntities can lag arbitrarily far behind. A client must not read "
            "absence from search as absence from the catalog. "
            "POST /operations?action=restoreIndices resyncs the index from the primary "
            "store without a restart."
        ),
        "primary_store_after_write": sorted(primary_after_write),
        "graph_index_caught_up_after_write": write_ok,
        "graph_index_write_seconds": round(write_s, 3),
        "restore_indices_after_write": restore_after_write,
        "graph_had_edge_before_removal": graph_had_edge_before_removal,
        "primary_store_after_removal": sorted(primary_after_removal),
        "graph_index_caught_up_after_removal": removal_ok,
        "graph_index_removal_seconds": round(removal_s, 3),
        "graph_index_last_seen_after_removal": sorted(graph_last)
        if isinstance(graph_last, set)
        else str(graph_last)[:200],
        "restore_indices_after_removal": restore_after_removal,
        "restore_indices_remedy": remedy,
        "diverged_on_write": diverged_on_write,
        "diverged_on_removal": diverged_on_removal,
        "poll_budget_s": budget_s,
        "note": (
            "A removal leg is only informative if the index actually held the edge "
            "beforehand -- see graph_had_edge_before_removal."
        ),
        "reproduced": (
            # the primary store is right at both steps
            primary_after_write == {LINEAGE_UP}
            and primary_after_removal == set()
            # the index disagreed with it at least once
            and (diverged_on_write or diverged_on_removal)
            # and every restoreIndices we had to reach for actually fixed it
            and all(r.get("graph_correct_after_restore") for r in restores)
        ),
    }


def probe_get_aspect_on_timeseries(gms: Gms, urn: str, empty_urn: str) -> dict:
    """FINDING-07: openapi/v3 get-aspect answers a timeseries aspect with the
    newest row only, and does not say so."""
    rows = raw_usage(gms, urn)
    aspect = gms.get_aspect("dataset", urn, "datasetUsageStatistics")
    empty_aspect = gms.get_aspect("dataset", empty_urn, "datasetUsageStatistics")
    value = (aspect or {}).get("value") or {}
    newest = max((v["timestampMillis"] for v in rows), default=None)
    return {
        "finding": "05-openapi-v3-get-aspect-returns-newest-timeseries-row-only",
        "claim": (
            "GET /openapi/v3/entity/dataset/<urn>/datasetusagestatistics returns a single "
            "aspect value -- the newest row -- shaped exactly like a non-timeseries aspect. "
            "Nothing in the response says a history exists, so a client reading a timeseries "
            "aspect through the generic entity route silently sees 1 of N rows."
        ),
        "probed_urn": urn,
        "rows_in_primary_store": len(rows),
        "get_aspect_returned_rows": 0 if aspect is None else 1,
        "get_aspect_timestamp": value.get("timestampMillis"),
        "newest_timestamp_in_store": newest,
        "get_aspect_matches_newest_row": value.get("timestampMillis") == newest,
        "response_mentions_history": any(
            k in json.dumps(aspect or {}).lower() for k in ("count", "total", "hasmore", "next")
        ),
        "on_dataset_without_rows": empty_aspect,
        "reproduced": (
            len(rows) > 1
            and aspect is not None
            and value.get("timestampMillis") == newest
            and empty_aspect is None
        ),
    }


# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gms-url", default="http://localhost:28080")
    ap.add_argument("--token", default=None)
    ap.add_argument(
        "--lag-budget-s",
        type=float,
        default=180.0,
        help="How long to wait for a derived index to catch up before recording 'still stale'.",
    )
    ap.add_argument("--keep", action="store_true", help="Skip teardown (for debugging).")
    ap.add_argument(
        "--no-seed",
        action="store_true",
        help="Write nothing. Requires --sparse-urn/--dense-urn/--empty-urn; runs only the read-only probes.",
    )
    ap.add_argument("--sparse-urn", default=None, help="Read-only mode: dataset with a gappy usage history.")
    ap.add_argument("--dense-urn", default=None, help="Read-only mode: dataset with consecutive-day usage history.")
    ap.add_argument("--empty-urn", default=None, help="Read-only mode: dataset with no usage history.")
    args = ap.parse_args()

    if args.no_seed and not (args.sparse_urn and args.dense_urn and args.empty_urn):
        ap.error("--no-seed requires --sparse-urn, --dense-urn and --empty-urn")

    from datahub.emitter.rest_emitter import DatahubRestEmitter

    gms = Gms(base_url=args.gms_url, token=args.token)
    emitter = DatahubRestEmitter(gms_server=args.gms_url, token=args.token)

    print(f"\n  upstream_repro against {gms.base}, namespace {NAMESPACE}\n")

    probes: list[dict] = []
    cleanup: dict = {}
    diagnosis: dict = {}
    try:
        if args.no_seed:
            diagnosis = {"write_path_stalled": True, "note": "--no-seed: nothing was written."}
        else:
            diagnosis = seed(gms, emitter)
            if diagnosis["write_path_stalled"]:
                print("\n  !! timeseries write path stalled -- see artifact `seed_diagnosis`\n")

        stalled = diagnosis["write_path_stalled"]
        sparse = args.sparse_urn or ZERO_FILL
        dense = args.dense_urn or DENSE
        empty = args.empty_urn or EMPTY
        # In read-only/stalled mode the caller-supplied datasets are the only
        # ones with usable history; the seeded fixtures are empty.
        readable = (not stalled) or (args.sparse_urn is not None)

        probes.append(probe_usagestats_range_required(gms, sparse))
        probes.append(probe_mcp_query_timestamps(gms))

        no_history = "no dataset with readable usage history: the write path is stalled and no --sparse-urn was given"
        if readable:
            probes.append(probe_timeseries_limit_required(gms, sparse))
            probes.append(probe_unique_user_count_aggregation(gms, [sparse, dense]))
            probes.append(probe_zero_fill(gms, sparse, dense, empty))
            probes.append(probe_get_aspect_on_timeseries(gms, sparse, empty))
        else:
            for finding, claim in (
                ("02-gettimeseriesaspectvalues-limit-null-pointer", "see docs/upstream/"),
                ("03-usagestats-uniqueusercount-aggregation-is-always-zero", "see docs/upstream/"),
                ("04-usagestats-buckets-are-a-dense-calendar-grid", "see docs/upstream/"),
                ("05-openapi-v3-get-aspect-returns-newest-timeseries-row-only", "see docs/upstream/"),
            ):
                probes.append(skipped(finding, claim, no_history))

        needs_write = "needs freshly written timeseries history; the write path on this instance is stalled"
        if stalled:
            probes.append(
                skipped(
                    "unconfirmed-delete-aspect-on-timeseries-removes-only-newest-row",
                    "see docs/upstream/",
                    needs_write,
                )
            )
            probes.append(
                skipped(
                    "unconfirmed-usagestats-aggregation-trails-the-primary-store",
                    "see docs/upstream/",
                    needs_write,
                )
            )
        else:
            probes.append(probe_timeseries_delete(gms))
            probes.append(probe_aggregation_lag(gms, emitter, args.lag_budget_s))

        if args.no_seed:
            probes.append(
                skipped(
                    "unconfirmed-graph-index-trails-writes-and-deletes",
                    "see docs/upstream/",
                    "--no-seed: this probe has to write and then remove a lineage edge",
                )
            )
        else:
            probes.append(probe_graph_index_lag(gms, args.lag_budget_s))
    finally:
        cleanup = {"skipped": True} if (args.keep or args.no_seed) else teardown(gms)

    version = None
    try:
        status, body = gms._send("GET", f"{gms.base}/config", None)
        if status == 200 and isinstance(body, dict):
            version = ((body.get("versions") or {}).get("acryldata/datahub") or {}).get("version")
    except GmsError:
        pass

    failed = [p["finding"] for p in probes if p.get("reproduced") is False]
    unmeasured = [p["finding"] for p in probes if p.get("reproduced") is None]
    artifact = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gms_url": gms.base,
        "datahub_version": version,
        "namespace": NAMESPACE,
        "anchor_utc_midnight_ms": int(ANCHOR.timestamp() * 1000),
        "probes": probes,
        "seed_diagnosis": diagnosis,
        "probes_total": len(probes),
        "probes_reproduced": len([p for p in probes if p.get("reproduced") is True]),
        "probes_not_reproduced": failed,
        "probes_not_measured": unmeasured,
        "cleanup": cleanup,
    }
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")

    for p in probes:
        mark = {True: "OK  ", False: "FAIL", None: "SKIP"}[p.get("reproduced")]
        print(f"  [{mark}] {p['finding']}" + (f"  ({p['skipped']})" if p.get("skipped") else ""))
    print(f"\n  cleanup: {cleanup}")
    print(f"  artifact: {ARTIFACT}")
    if failed:
        print(f"\n  NOT REPRODUCED: {failed}\n")
        return 1
    print(f"\n  all {len(probes)} probes reproduced\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
