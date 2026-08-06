# Entscheid: Technik der Werkbank

*2026-08-07 · betrifft `ui/` (neu)*

## Was stand zur Wahl

**A — React + Vite.** Komponenten, Zustandsverwaltung, `vite build` erzeugt einen
statischen Ordner.

**B — Next.js / SvelteKit.** Wie A, plus Server-Teil für den Live-Modus in einem
Werkzeug.

**C — Eine statische Seite ohne Bauschritt** (HTML + CSS + JavaScript-Module), im
Live-Modus ausgeliefert von einem kleinen Python-Server aus der Standardbibliothek, der
zugleich als Proxy zur GMS dient.

## Was gewählt

**C.** Drei Dateien ohne Abhängigkeiten (`ui/werkbank.html`, `ui/werkbank.css`,
`ui/werkbank.js`), plus `ui/serve.py` (~120 Zeilen `http.server`) für den Live-Modus.

Zwei Betriebsarten, dieselbe Seite:

| Modus | Datenquelle | Knöpfe |
|---|---|---|
| **live** | `ui/serve.py` auf Port **8899** → `probate/`-Module → GMS 28080 | schreiben wirklich |
| **Aufzeichnung** | `ui/recorded/*.json` per `fetch()` relativ | deaktiviert, mit Begründung im Knopf |

Der Modus wird nicht geraten: `werkbank.js` fragt beim Start `GET /api/mode`. Antwortet
niemand (Datei per `file://` oder `python -m http.server` geöffnet), ist es
**Aufzeichnung** — der sichere Rückfall, sichtbar im Kopfbereich gekennzeichnet.

## Warum

**1. CORS entscheidet das, nicht der Geschmack.** Ein Browser, der von `file://` oder
`localhost:5173` direkt gegen `localhost:28080` spricht, braucht von GMS einen
`Access-Control-Allow-Origin`-Kopf. Ob DataHubs GMS den für fremde Ursprünge sendet, ist
auf dieser Instanz **nicht gemessen** — und der Preflight-`OPTIONS` auf
`/openapi/v3/entity/...` kommt noch dazu. Das ist genau die Sorte Unbekanntes, das man am
Samstagabend nicht debuggen will. Ein Proxy im selben Ursprung löscht die Frage, statt sie
zu beantworten.

**2. Der Proxy muss ohnehin existieren, weil die Knöpfe Python sind.** „Kante eintragen"
ist kein GMS-Aufruf, sondern `correct.apply_proposal()` über `writeback.Writeback` — mit
Journal, Vorher-Sicherung und Rückwärtsgang. Diese Disziplin im Browser nachzubauen wäre
eine zweite Wahrheit über den einzigen Schreibweg. `ui/serve.py` importiert stattdessen
dieselben Module wie die CLI. Damit ist der Proxy kein Zusatz, sondern der Ort, an dem die
Knöpfe leben — und A/B bräuchten ihn genauso, nur zusätzlich zu einem Bauschritt.

**3. Bauzeit ist Risiko, nicht Komfort.** `node v22.9.0` und `npm 11.6.4` sind vorhanden
(gemessen), aber `npm install` zieht am Samstagabend hunderte Pakete gegen ein Netz, das
niemand kontrolliert, und `vite build` ist ein zusätzlicher Schritt zwischen „Code
geändert" und „Joel sieht es". Der statische Export ist hier `cp -r ui/ examples/ui/` —
kein Werkzeug dazwischen, das ausfallen kann.

**4. React löst hier nichts.** Der Bildschirm hat vier Bereiche und sechs Knöpfe. Der
Zustand ist ein Objekt (`ledger.json`) plus eine Protokollzeile-Liste. Die harten
Anforderungen aus der Spec — beruhigende Farbgebung, zwei Quellenfarben durchgehend,
sichtbarer Tastaturfokus, helles **und** dunkles Thema gleichwertig, breite Inhalte
scrollen im eigenen Container — sind alle CSS. Ein Rahmenwerk trüge dazu nichts bei und
brächte einen Bündelungsschritt mit.

**5. Port 8899, ausdrücklich.** Nicht 8080 (Joels WhatsApp-Bridge), nicht 8081 (die
nicht-existierende Schema-Registry, deren Adresse schon einmal Zeit gekostet hat), nicht
3000 (Cockpit-Oberfläche).

## Was müsste passieren, damit es falsch war

- **Die Ledger-Ansicht braucht Virtualisierung.** Bei 5'000 Kanten im DOM wird die Seite
  zäh. Gegenmittel ist im Plan: die Werkbank zeigt das Register des Demo-Laufs (Dutzende
  Kanten), die Lasttest-Zahlen kommen aus der CLI und stehen als Zahlen daneben — die
  Werkbank ist das Labor, nicht der Ersatz für den Messlauf. Falsch wäre der Entscheid
  erst, wenn die Demo selbst tausende Zeilen zeigen müsste.
- **Die Gestaltungsvorgaben fallen ohne Komponentensystem auseinander.** Konkret: dieselbe
  Zustandsfarbe an drei Stellen leicht verschieden. Gegenmittel: alle Farben und Abstände
  ausschliesslich als CSS-Custom-Properties in einem `:root`-Block, nirgends ein
  Literalwert im Regelwerk. Ein Test dafür ist in P5 eingeplant (Suche nach `#`-Literalen
  ausserhalb des Token-Blocks).
- **Der Proxy braucht mehr als GET/POST-Weiterleitung** (Streaming, WebSocket für das
  Live-Protokoll). Der Plan sieht dafür Abfrage im Intervall vor (`GET /api/log?since=N`),
  weil das mit `http.server` funktioniert. Bräuchte das Protokoll echtes Streaming, wäre
  ein richtiger Server die bessere Wahl gewesen.
