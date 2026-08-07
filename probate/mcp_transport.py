"""Der zweite Weg zur Ko-Okkurrenz: DataHubs eigener MCP-Server.

WARUM es diesen Weg gibt
========================
probate liest den Katalog bisher ausschliesslich ueber GraphQL/OpenAPI
(`probate/gms.py`). Das ist der belastbare Weg, aber es ist nicht der Weg,
den DataHub selbst als Agenten-Schnittstelle anbietet. Dieses Modul macht
den MCP-Server zu einer WAEHLBAREN zweiten Quelle fuer genau EINEN Lesevorgang
-- die Ko-Okkurrenz -- damit beide Wege gegen denselben Katalogzustand
laufen und ihr Ergebnis UND ihre Kosten vergleichbar werden.

Nicht mehr als einen Lesevorgang, und das mit Absicht: der MCP-Server
liefert fuer die Nutzungs-Zeitachse (`fetch_usage`) nachweislich nichts
Gleichwertiges (s. "Was der MCP-Server nicht kann" unten). Einen Weg
anzubieten, der die Haelfte der Belege still weglaesst, waere genau die
Sorte Behauptung, gegen die dieses Projekt antritt.

Der Vertrag ist identisch mit `probate.ledger.fetch_cooccurrence`:
`(dict[Ziel-URN, list[Query-URN]], echte Gesamtzahl)`. Ein Fehlschlag wirft
`McpError`; es gibt keinen Zweig, der bei einem Problem ein leeres Mapping
zurueckgibt. Ein leeres Mapping heisst hier ausschliesslich "gefragt und
nichts gefunden", nie "konnte nicht fragen" (`.claude/rules/verification.md`:
eine gescheiterte Abfrage ist keine Abwesenheit).

GEMESSEN (2026-08-07, `harness/runs/mcp-probe.json`)
====================================================
Gepinnt auf mcp-server-datahub **0.6.0** gegen GMS v1.5.0.6 (localhost:28080).

* Das Werkzeug heisst `get_dataset_queries`. Es antwortet mit `total`,
  `start`, `count` und `queries[]`; jeder Eintrag traegt `urn` und
  `subjects` -- eine vom Server bereits deduplizierte Liste der
  Dataset-URNs, die diese Query beruehrt. Das ist exakt die Ko-Okkurrenz.
* Damit braucht dieser Weg **einen** Aufruf, wo der GraphQL-Weg
  1 + N braucht (eine Suche, danach pro Query ein `querysubjects`-Aspekt).
* `subjects` ist server-seitig auf Dataset-URNs reduziert
  (`_deduplicate_subjects` in `tools/dataset_queries.py` verwirft alles,
  was kein `subject["dataset"]["urn"]` hat). Der GraphQL-Weg liest den
  rohen `querysubjects`-Aspekt und sieht auch Spalten-Subjects
  (`schemaField`). Fuer die Kanten-Ko-Okkurrenz auf Dataset-Ebene ist das
  identisch -- gemessen, nicht angenommen (s. Vergleich im Artefakt).

Was der MCP-Server NICHT kann (0.6.0, im Quelltext belegt)
----------------------------------------------------------
`src/mcp_server_datahub/gql/queries.gql` fragt `properties.created` gar
nicht ab (der ganze Block ist auskommentiert) und von `lastModified` nur
den `actor`, nicht die `time`. Eine Query-Entitaet kommt ueber diesen Weg
also **ohne jeden Zeitstempel** zurueck -- live bestaetigt, die Antwort
enthaelt `lastModified: {actor: ...}` und sonst nichts Zeitliches. Die
Alters-Achse von probate (`dead` vs. `confirmed`) haengt darum
unveraendert an den Dataset-Nutzungs-Buckets aus `fetch_usage`, fuer die
der MCP-Server ueberhaupt kein Werkzeug anbietet.

Trunkierung wird NICHT geschluckt
---------------------------------
`get_dataset_queries` paginiert (`start`/`count`, Vorgabe `count=10`).
Wenn `total` groesser ist als die Zahl zurueckgegebener Queries, fehlen
Belege -- dann wirft dieses Modul, statt eine unvollstaendige Karte als
vollstaendig auszugeben. Der GraphQL-Weg deckelt bei 200 und meldet `total`
getrennt; hier ist die Regel strenger, weil ein Aufrufer die Deckelung
sonst nicht sehen wuerde.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from typing import Any, Callable, Protocol

# Vorgabe-Pin. `@latest` ist kein Pin, sondern eine Frage, die zu jedem
# Zeitpunkt anders beantwortet werden kann.
#
# Genauer Stand der Belege, weil hier zwei verschiedene Dinge leicht
# durcheinandergehen: die Projektnotiz vom 2026-08-02 haelt fest, dass
# `uvx mcp-server-datahub@latest` damals 0.4.0 ergab. GEMESSEN am
# 2026-08-07 (`harness/runs/mcp-probe.json`, Feld `latest_resolution`)
# ergibt derselbe Befehl 0.6.0 -- mit und ohne `--python`-Pin. Der alte
# Wert ist heute also NICHT reproduzierbar; warum, ist offen (ein
# uv-Cache, eine andere Interpreter-Wahl, ein anderer Netzzustand). Was
# belegt bleibt: 0.5.0 und alles danach verlangt Python >= 3.11 (PyPI-
# Metadaten), 0.4.0 nur >= 3.10 -- ein Lauf ohne Interpreter-Pin kann
# darum grundsaetzlich auf einer aelteren Version landen.
#
# Und das ist der Grund fuer die Zahl hier: 0.4.0 und 0.6.0 registrieren
# verschiedene Werkzeugmengen. Eine Messung, die "der Server hat N
# Werkzeuge" sagt, ohne die Version zu nennen, ist keine Messung.
DEFAULT_MCP_VERSION = "0.6.0"

# Muss mit `probate.targets._QUERY_SEARCH_Q` (count: 200) uebereinstimmen,
# sonst vergleicht der Doppellauf zwei verschieden tief geschoepfte Mengen.
DEFAULT_QUERY_COUNT = 200


class McpError(RuntimeError):
    pass


class ToolCaller(Protocol):
    """Ein Aufruf gegen den MCP-Server: Werkzeugname + Argumente -> JSON.

    Existiert als eigene Naht, damit `cooccurrence_from_mcp` OHNE Server,
    ohne Netz und ohne Unterprozess testbar ist -- die Tests reichen eine
    Funktion herein, die eine feste Antwort liefert."""

    def __call__(self, tool: str, args: dict[str, Any]) -> Any: ...


def cooccurrence_from_mcp(
    call_tool: ToolCaller,
    urn: str,
    count: int = DEFAULT_QUERY_COUNT,
) -> tuple[dict[str, list[str]], int]:
    """Ko-Okkurrenz MIT Beleg ueber `get_dataset_queries`.

    Rueckgabe wie `probate.ledger.fetch_cooccurrence`: Ziel-URN -> Liste
    der Query-URNs, die Fokus und Ziel gemeinsam beruehren, plus die ECHTE
    Gesamtzahl der Query-Treffer (`total` aus der Antwort, nicht
    `len(queries)`).

    Der Fokus selbst steht immer in seinen eigenen `subjects` und wird
    herausgefiltert -- sonst waere jedes Dataset sein eigener Konsument.
    """
    payload = call_tool("get_dataset_queries", {"urn": urn, "count": count})
    if not isinstance(payload, dict):
        raise McpError(
            f"get_dataset_queries lieferte {type(payload).__name__}, erwartet ein Objekt"
        )
    if "total" not in payload:
        raise McpError(
            "get_dataset_queries-Antwort ohne 'total' -- ohne die echte "
            f"Gesamtzahl waere jedes queries_seen geraten. Antwort: {str(payload)[:300]}"
        )
    total = int(payload["total"] or 0)
    queries = payload.get("queries")
    if queries is None:
        queries = []
    if not isinstance(queries, list):
        raise McpError(f"'queries' ist {type(queries).__name__}, erwartet eine Liste")

    if len(queries) < total:
        raise McpError(
            f"get_dataset_queries: total={total}, aber nur {len(queries)} Queries "
            f"zurueckgegeben (count={count}). Die fehlenden Belege wuerden eine "
            "unvollstaendige Ko-Okkurrenz als vollstaendig aussehen lassen."
        )

    out: dict[str, list[str]] = {}
    for entry in queries:
        if not isinstance(entry, dict) or not entry.get("urn"):
            raise McpError(f"Query-Eintrag ohne 'urn': {str(entry)[:200]}")
        q_urn = entry["urn"]
        for other in entry.get("subjects") or []:
            # `_deduplicate_subjects` im Server liefert flache Strings.
            # Alles andere ist eine Formaenderung, die stillschweigend
            # falsche Kanten erzeugen wuerde -- also lieber laut sein.
            if not isinstance(other, str):
                raise McpError(
                    f"'subjects' enthaelt {type(other).__name__} statt einer URN: "
                    f"{str(other)[:200]}"
                )
            if other != urn:
                out.setdefault(other, []).append(q_urn)
    return out, total


def make_cooccurrence_fetcher(
    call_tool: ToolCaller,
    count: int = DEFAULT_QUERY_COUNT,
) -> Callable[[Any, str], tuple[dict[str, list[str]], int]]:
    """Adapter auf die Signatur von `fetch_cooccurrence(gms, urn)`.

    Das `gms`-Argument wird fuer die eigentliche Abfrage nicht gebraucht --
    dieser Weg spricht mit dem MCP-Server, nicht mit GMS. Trotzdem wird
    ein `calls`-Zaehler auf dem uebergebenen Objekt hochgezaehlt, falls es
    einen hat (`probate.ledger._Counting`): ein MCP-Werkzeugaufruf ist ein
    Netz-Rundlauf wie jeder andere, und ein Lauf-Artefakt, das ihn nicht
    zaehlt, wuerde den MCP-Weg guenstiger aussehen lassen, als er ist.
    """

    def fetch(gms: Any, urn: str) -> tuple[dict[str, list[str]], int]:
        if hasattr(gms, "calls"):
            try:
                gms.calls += 1
            except Exception:  # pragma: no cover - reine Zaehl-Buchhaltung
                pass
        return cooccurrence_from_mcp(call_tool, urn, count=count)

    # `ledger.run()` liest dieses Attribut, um im Lauf-Artefakt festzuhalten,
    # WELCHER Weg die Zahlen geliefert hat.
    fetch.source_name = "mcp"  # type: ignore[attr-defined]
    return fetch


class McpSession:
    """Ein laufender stdio-MCP-Server als Unterprozess, sync benutzbar.

    Der MCP-Client des offiziellen SDK ist asynchron; probates CLI ist es
    nicht. Statt die ganze Kette async zu faerben laeuft hier EIN
    Hintergrund-Thread mit eigenem Event-Loop, an den `call_tool` seine
    Coroutine uebergibt. Dadurch bleibt die Naht `ToolCaller` eine ganz
    normale, synchrone Funktion -- und damit testbar.

    Der Start ist teuer (uvx-Aufloesung + Server-Boot; gemessen ~29 s kalt,
    s. Artefakt), der einzelne Werkzeugaufruf danach billig. Genau darum
    ist die Sitzung ein Objekt mit Lebensdauer und keine Funktion, die pro
    Aufruf einen Server hochfaehrt.

    `mcp` ist eine optionale Abhaengigkeit und wird ERST hier importiert:
    wer den GraphQL-Weg benutzt (Vorgabe), soll das Paket nicht brauchen.
    """

    def __init__(
        self,
        gms_url: str,
        version: str = DEFAULT_MCP_VERSION,
        token: str | None = None,
        mutation_enabled: bool = False,
        telemetry_enabled: bool | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> None:
        self.gms_url = gms_url
        self.version = version
        self.token = token
        self.mutation_enabled = mutation_enabled
        self.telemetry_enabled = telemetry_enabled
        self.extra_env = dict(extra_env or {})
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session: Any = None
        self._stack: Any = None
        self.tools: list[dict[str, Any]] = []
        # Groesse der letzten Werkzeug-Antwort in Zeichen. Vorbelegt mit
        # None, damit "noch nichts gerufen" und "Antwort war leer" (0)
        # unterscheidbar bleiben -- ein Messwert, der bei 0 startet,
        # behauptet eine Messung, die nie stattgefunden hat.
        self.last_response_chars: int | None = None

    # -- Umgebung ---------------------------------------------------------
    def server_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["DATAHUB_GMS_URL"] = self.gms_url
        if self.token:
            env["DATAHUB_GMS_TOKEN"] = self.token
        env["TOOLS_IS_MUTATION_ENABLED"] = "true" if self.mutation_enabled else "false"
        if self.telemetry_enabled is not None:
            env["DATAHUB_TELEMETRY_ENABLED"] = "true" if self.telemetry_enabled else "false"
        env.update(self.extra_env)
        return env

    def server_argv(self) -> list[str]:
        # `--from mcp-server-datahub==<version>` statt `@latest`: s.
        # DEFAULT_MCP_VERSION. `--python 3.11`, weil `python` auf dieser
        # Maschine ein 3.9-Alias ist und mcp-server-datahub >= 0.5.0
        # Python >= 3.11 verlangt -- ohne den Pin faellt uv stillschweigend
        # auf die letzte 3.10-taugliche Version 0.4.0 zurueck.
        return [
            "uvx", "--python", "3.11",
            "--from", f"mcp-server-datahub=={self.version}",
            "mcp-server-datahub", "--transport", "stdio",
        ]

    # -- Lebenszyklus -----------------------------------------------------
    def __enter__(self) -> "McpSession":
        self.open()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def open(self) -> None:
        try:
            from mcp import ClientSession, StdioServerParameters  # noqa: F401
            from mcp.client.stdio import stdio_client  # noqa: F401
        except ImportError as e:
            raise McpError(
                "Das Paket 'mcp' fehlt. Der MCP-Weg ist optional; installiere ihn "
                "z.B. mit `uv run --python 3.11 --with mcp ...`."
            ) from e

        loop = asyncio.new_event_loop()
        self._loop = loop
        self._thread = threading.Thread(target=loop.run_forever, daemon=True)
        self._thread.start()
        try:
            self._run(self._open_async())
        except Exception:
            self.close()
            raise

    async def _open_async(self) -> None:
        import contextlib

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        argv = self.server_argv()
        params = StdioServerParameters(
            command=argv[0], args=argv[1:], env=self.server_env()
        )
        stack = contextlib.AsyncExitStack()
        self._stack = stack
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._session = session
        listed = await session.list_tools()
        self.tools = [
            {
                "name": t.name,
                "read_only_hint": bool(
                    getattr(t.annotations, "readOnlyHint", None)
                    or getattr(t.annotations, "read_only_hint", None)
                )
                if t.annotations
                else False,
            }
            for t in listed.tools
        ]

    def close(self) -> None:
        loop = self._loop
        if loop is None:
            return
        if self._stack is not None:
            try:
                self._run(self._stack.aclose())
            except Exception:
                pass
            self._stack = None
        self._session = None
        loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=10)
        self._thread = None
        self._loop = None

    def _run(self, coro: Any) -> Any:
        loop = self._loop
        if loop is None:
            raise McpError("Sitzung ist nicht offen")
        return asyncio.run_coroutine_threadsafe(coro, loop).result()

    # -- Werkzeugaufruf ---------------------------------------------------
    def call_tool(self, tool: str, args: dict[str, Any]) -> Any:
        if self._session is None:
            raise McpError("Sitzung ist nicht offen -- open() zuerst")
        result = self._run(self._session.call_tool(tool, args))
        if getattr(result, "isError", False):
            raise McpError(f"{tool} meldete einen Fehler: {str(result.content)[:400]}")
        text = "".join(
            block.text for block in result.content if getattr(block, "type", "") == "text"
        )
        self.last_response_chars = len(text)
        if not text:
            raise McpError(f"{tool} lieferte keinen Text-Block zurueck")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise McpError(f"{tool} lieferte kein JSON: {text[:300]}") from e
