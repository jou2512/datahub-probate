"""Der einzige Weg nach draussen.

Zwei Fallen sind hier eingebaut, damit sie niemand sonst noch einmal tritt:

1. POST /openapi/v3/entity/<typ> nimmt eine LISTE. Ein Objekt liefert
   HTTP 200 und ein leeres [] - erfolgreich aussehender Nichtschreibvorgang.
2. GraphQL meldet Fehler mit HTTP 200. Wer nur den Status-Code prueft,
   haelt eine Fehlermeldung fuer ein Ergebnis.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable


class GmsError(RuntimeError):
    pass


def _urllib_transport(method: str, url: str, payload: Any) -> tuple[int, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else None)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:400]


class Gms:
    def __init__(
        self,
        base_url: str = "http://localhost:18080",
        timeout: int = 30,
        transport: Callable[[str, str, Any], tuple[int, Any]] | None = None,
    ) -> None:
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self._send = transport or _urllib_transport

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables
        status, body = self._send("POST", f"{self.base}/api/graphql", payload)
        if status != 200 or not isinstance(body, dict):
            raise GmsError(f"GraphQL HTTP {status}: {str(body)[:200]}")
        if body.get("errors"):
            raise GmsError(f"GraphQL meldet Fehler: {json.dumps(body['errors'])[:300]}")
        return body.get("data") or {}

    def upsert(self, entity_type: str, records: list[dict], sync: bool = True) -> list[dict]:
        if not isinstance(records, list):
            raise GmsError(
                "upsert verlangt eine Liste. Ein einzelnes Objekt liefert HTTP 200 "
                "und schreibt nichts."
            )
        suffix = "?async=false" if sync else ""
        url = f"{self.base}/openapi/v3/entity/{entity_type.lower()}{suffix}"
        status, body = self._send("POST", url, records)
        if status != 200 or not isinstance(body, list):
            raise GmsError(f"upsert {entity_type} HTTP {status}: {str(body)[:200]}")
        if len(body) != len(records):
            raise GmsError(
                f"upsert {entity_type}: {len(records)} gesendet, {len(body)} geschrieben"
            )
        return body

    def get_aspect(self, entity_type: str, urn: str, aspect: str) -> dict | None:
        url = f"{self.base}/openapi/v3/entity/{entity_type.lower()}/{urn}/{aspect.lower()}"
        status, body = self._send("GET", url, None)
        if status == 404:
            return None
        if status != 200:
            raise GmsError(f"get_aspect HTTP {status}: {str(body)[:200]}")
        return body if isinstance(body, dict) else None

    def delete_aspect(self, entity_type: str, urn: str, aspect: str) -> None:
        """Fuer den Rueckwaertsgang: ein Aspekt, den es vorher nicht gab,

        wird beim Revert nicht auf einen erfundenen Leerwert gesetzt,
        sondern geloescht. Live gegen 28080 verifiziert (2026-08-06):
        DELETE /openapi/v3/entity/<typ>/<urn>/<aspekt> -> HTTP 200,
        get_aspect() liefert danach wieder None.
        """
        url = f"{self.base}/openapi/v3/entity/{entity_type.lower()}/{urn}/{aspect.lower()}"
        status, body = self._send("DELETE", url, None)
        if status != 200:
            raise GmsError(f"delete_aspect {entity_type}.{aspect} HTTP {status}: {str(body)[:200]}")
