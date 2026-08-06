"""Der einzige Weg nach draussen.

Fallen sind hier eingebaut, damit sie niemand sonst noch einmal tritt:

1. POST /openapi/v3/entity/<typ> nimmt eine LISTE. Ein Objekt liefert
   HTTP 200 und ein leeres [] - erfolgreich aussehender Nichtschreibvorgang.
2. GraphQL meldet Fehler mit HTTP 200. Wer nur den Status-Code prueft,
   haelt eine Fehlermeldung fuer ein Ergebnis.
3. Live-Fund (Jury-Review 2026-08-06): ohne Token authentifiziert probate
   sich als urn:li:corpuser:__datahub_system -- das funktioniert nur gegen
   eine Instanz OHNE Zugriffskontrolle. Gegen eine echte, abgesicherte GMS
   braucht es ein Personal Access Token. Vorher gab es dafuer keinen Weg
   ausser einem Code-Kommentar in succession.py -- jetzt --token/DATAHUB_TOKEN.
4. Security-Review-Fund (C3, 2026-08-07): urllib.request.HTTPRedirectHandler
   kopiert alle Header ausser Content-Length/Content-Type unveraendert auf
   das Redirect-Ziel, ohne Host-Pruefung -- und urlopen() folgt 3xx-Antworten
   per Default (gemessen auf dieser Maschine, Python 3.11.9/3.11.2). Ein
   einzelnes "302 Location: https://collector.attacker/x" von der GMS-Basis-
   URL wuerde den Bearer-PAT an ein beliebiges Ziel weiterreichen. GMS
   redirected bei einem regulaeren API-Aufruf nie -- also wird global ein
   Opener installiert, der 3xx NICHT folgt (siehe _install_no_redirect_opener
   unten).
5. Security-Review-Fund (C4, 2026-08-07): get_aspect/delete_aspect/upsert
   interpolieren die URN unquotiert in den OpenAPI-Pfad. "../" oder "?" in
   einer URN schreibt den Request-Pfad um. _validate_urn() prueft das vor
   jeder Interpolation (siehe dort fuer die erlaubte Grammatik).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Callable


class GmsError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """WHY (Finding C3): redirect_request() -> None laesst 3xx NICHT folgen.

    HTTPRedirectHandler kopiert sonst alle Header (inkl. Authorization) auf
    das Redirect-Ziel, ohne den Host zu pruefen -- ein Redirect-Handler ist
    damit ein eingebauter Header-Leak. GMS redirected API-Aufrufe nie, also
    surfaced ein 3xx als HTTPError(code) und faellt in die bestehende
    non-200-Behandlung (-> lauter GmsError statt stillem Header-Leak)."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _install_no_redirect_opener() -> None:
    """Installiert den Opener global fuer urllib.request.urlopen().

    Additiv statt eines Umbaus von send(): die einzige andere urlopen()-
    Stelle im Repo (harness/preflight.py) spricht ebenfalls nur mit GMS,
    fuer die dieselbe Regel gilt (GMS redirected nie). Empirisch geprueft
    (2026-08-07, Python 3.11.2): ohne den Opener folgt urlopen() dem 302
    und der Authorization-Header kommt beim Redirect-Ziel an; mit
    install_opener(build_opener(_NoRedirect)) wirft urlopen() stattdessen
    HTTPError(302), das Redirect-Ziel wird nie kontaktiert.
    """
    urllib.request.install_opener(urllib.request.build_opener(_NoRedirect))


_install_no_redirect_opener()


# Erlaubte URN-Grammatik fuer die Pfad-Interpolation (Finding C4).
# Verschachtelte DataHub-URNs enthalten legitim ( ) , : und auch / (manche
# Plattform-Datensatznamen, z.B. postgres-Schemas) -- deshalb wird / NICHT
# verboten. Verboten sind nur Zeichen/Teilstrings, die eine OpenAPI-Pfad-
# Interpolation umschreiben koennen: " \ Leerraum { } ? # sowie ".." (Path-
# Traversal). Alternative waere Prozent-Encoding der URN, aber ob GMS
# encodierte URNs in Pfaden akzeptiert, ist heute Nacht nicht geprueft --
# Validierung statt Encoding ist der risikoaermere Weg.
URN_RE = re.compile(r'^urn:li:[a-zA-Z]+:[^"\\{}?#\s]+$')


def _validate_urn(urn: str) -> None:
    if not URN_RE.match(urn) or ".." in urn:
        raise GmsError(f"URN verletzt das erlaubte Pfad-Muster: {urn[:200]!r}")


def _urllib_transport(token: str | None) -> Callable[[str, str, Any], tuple[int, Any]]:
    def send(method: str, url: str, payload: Any) -> tuple[int, Any]:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode()
                return r.status, (json.loads(raw) if raw.strip() else None)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()[:400]

    return send


class Gms:
    def __init__(
        self,
        # Security-Review-Fund (I1, 2026-08-07): 18080 = showcase-ecommerce,
        # die fremde Messdaten-Instanz, gegen die die Geschwister-Einreichung
        # datahub-attest ihre Zahlen veroeffentlicht hat -- dort schreiben
        # entwertet zwei Einreichungen. 8080 = private Bridge, niemals.
        # 28080 ist die einzige Instanz, gegen die dieses Projekt schreiben darf.
        base_url: str = "http://localhost:28080",
        timeout: int = 30,
        token: str | None = None,
        transport: Callable[[str, str, Any], tuple[int, Any]] | None = None,
    ) -> None:
        """`token`: explizites Personal Access Token. Fehlt es, wird
        DATAHUB_TOKEN aus der Umgebung gelesen (leer -> kein Header,
        genau das bisherige, jetzt bewusste statt zufaellige Verhalten
        gegen unabgesicherte lokale Instanzen)."""
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.token = token if token is not None else os.environ.get("DATAHUB_TOKEN")
        self._send = transport or _urllib_transport(self.token)

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
        for record in records:
            urn = record.get("urn") if isinstance(record, dict) else None
            if urn is not None:
                _validate_urn(urn)
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
        _validate_urn(urn)
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
        _validate_urn(urn)
        url = f"{self.base}/openapi/v3/entity/{entity_type.lower()}/{urn}/{aspect.lower()}"
        status, body = self._send("DELETE", url, None)
        if status != 200:
            raise GmsError(f"delete_aspect {entity_type}.{aspect} HTTP {status}: {str(body)[:200]}")
