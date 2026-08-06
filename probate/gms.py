"""Der einzige VALIDIERTE Weg nach draussen.

harness/preflight.py spricht GMS zusaetzlich direkt an (eigener urlopen-
Aufruf, kein Import von hier) -- ohne den Redirect-Schutz aus Fund C3
weiter unten. Heute Nacht unkritisch, weil preflight.py nie einen Token
setzt (siehe dessen eigenes Docstring), aber es ist NICHT derselbe Schutz.

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
   redirected bei einem regulaeren API-Aufruf nie -- also wird ein Opener
   gebaut, der 3xx NICHT folgt, und explizit in send() verwendet (kein
   globaler install_opener()-Seiteneffekt -- Review-Runde 2, 2026-08-07).
5. Security-Review-Fund (C4, 2026-08-07, verschaerft in Runde 2): reine
   Denylists gegen Pfad-Traversal sind ein bekannt schwaches Muster --
   Runde 1 verbot ".." als Teilstring, liess aber Prozent-Encoding
   ("%2e%2e") durch, weil urllib das erst beim eigentlichen Request
   dekodiert, nicht beim String-Vergleich. _validate_urn() ist deshalb
   eine ALLOWLIST: nur Zeichen, die tatsaechlich in einer URN in diesem
   Repo vorkommen (siehe dort fuer die Grammatik und den Beleg-Grep).
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


# Module-level, einmal gebauter Opener statt eines globalen
# install_opener()-Seiteneffekts (Review-Runde 2, 2026-08-07): dieselbe
# Redirect-Sperre, aber urllib.request.urlopen() bleibt fuer jeden anderen
# Aufrufer im Prozess unveraendert -- nur send() unten benutzt _OPENER
# explizit. Empirisch geprueft (2026-08-07, Python 3.11.2): ohne den
# Opener folgt urlopen() dem 302 und der Authorization-Header kommt beim
# Redirect-Ziel an; mit _OPENER.open() wirft es stattdessen HTTPError(302),
# das Redirect-Ziel wird nie kontaktiert.
_OPENER = urllib.request.build_opener(_NoRedirect)


# Erlaubte URN-Grammatik fuer die Pfad-Interpolation (Finding C4).
#
# ALLOWLIST statt Denylist (Review-Runde 2, 2026-08-07): Runde 1 verbot
# nur einzelne Zeichen + die Teilzeichenkette "..". Live widerlegt --
# "urn:li:dataset:%2e%2e%2fadmin%2fsecret" enthaelt keines der verbotenen
# Zeichen und wurde akzeptiert, weil urllib "%2e" erst beim eigentlichen
# Request dekodiert, nicht beim String-Vergleich hier. Denylists gegen
# Traversal sind ein bekannt schwaches Muster (%2e%2e ist der erste
# Scanner-Versuch) -- ob GMS %2e ueberhaupt normalisiert, ist ungeprueft,
# und genau diese Ungewissheit ist der Punkt.
#
# Grammatik per Beleg statt Vermutung: `grep -rohE "urn:li:[A-Za-z]+:..."
# probate/ harness/ examples/ probate_action/ ui/` (2026-08-07) --
# jedes Zeichen ausserhalb [A-Za-z0-9_.:,()/-] in echten URN-Literalen
# war ausschliesslich "{" / "}", und die stammen alle aus Python-Format-
# Platzhaltern VOR der Interpolation (z.B. "{PLATFORM}", "{qid}",
# "{n:05d}") -- nie aus einer tatsaechlichen Laufzeit-URN. Kein einziges
# "%" in irgendeiner URN im Repo. Erlaubt: Gross-/Kleinbuchstaben, Ziffern,
# `_ . : , ( ) -` und `/` (Plattform-Datensatznamen wie postgres-Schemas
# brauchen den Slash legitim). Alles andere -- inkl. "%", NUL, Steuer-
# zeichen, Leerraum, `"` `\` `{` `}` `?` `#` -- wird abgelehnt.
#
# Die Allowlist erlaubt weiterhin einzelne "." und "/", also bleibt der
# explizite ".."-Substring-Check noetig: er faengt Traversal aus echten
# (nicht prozent-encodierten) Zeichen wie "urn:li:dataset:../../etc".
#
# Alternative waere Prozent-Encoding der URN vor dem Senden, aber ob GMS
# encodierte URNs in Pfaden akzeptiert, ist heute Nacht nicht geprueft --
# Validierung statt Encoding ist der risikoaermere Weg.
URN_RE = re.compile(r"^urn:li:[A-Za-z]+:[A-Za-z0-9_.:,()/-]+$")


def _validate_urn(urn: object) -> None:
    if not isinstance(urn, str):
        raise GmsError(f"URN muss ein String sein, ist {type(urn).__name__}")
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
            with _OPENER.open(req, timeout=30) as r:
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
