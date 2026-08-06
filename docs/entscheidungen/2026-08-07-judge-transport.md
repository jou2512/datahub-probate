# Entscheid: Transport für den Modellaufruf

*2026-08-07 · betrifft `probate/judge.py` (neu)*

## Was stand zur Wahl

**A — Anthropic-SDK direkt** (`anthropic.Anthropic().messages.create(...)`).
Sauberste Schnittstelle, strukturierte Antwort, Token-Zählung eingebaut.

**B — Claude Code CLI headless** (`claude -p "<prompt>" --output-format json`) als
Unterprozess.

**C — Kein Modell.** Schicht 2 streichen, nur der deterministische Befund.

## Was gewählt

**Rahmen: ein injizierbares `Callable[[str], str]`. Vorgabe-Implementierung: B
(`claude -p`), mit hartem Timeout und Rückfall auf den deterministischen Befund bei jedem
Fehler.**

```python
JudgeTransport = Callable[[str], str]          # prompt -> rohe Antwort

def claude_cli_transport(timeout: int = 60, binary: str = "claude") -> JudgeTransport
def judge_edge(verdict, up_ctx, down_ctx, transport: JudgeTransport | None) -> Judgement
```

`transport=None` bedeutet: gar kein Modellaufruf, sofort deterministischer Befund. Alle
Tests laufen gegen handgeschriebene Fake-Callables; **kein Test startet je einen Prozess**.

## Warum

**1. Der Schlüssel ist messbar nicht da, die CLI messbar schon.** Gemessen 2026-08-07 auf
dieser Maschine:

```
claude --version   -> 2.1.223 (Claude Code)
$ANTHROPIC_API_KEY -> nicht gesetzt
```

Option A würde also am Wochenende an einer Umgebungsvariable scheitern, die niemand
setzen kann, ohne ein Konto anzufassen (HITL, `CLAUDE.md` Regel 7). Eine Vorgabe, die auf
der Zielmaschine nicht startet, ist keine Vorgabe.

**2. Das injizierbare Callable ist der eigentliche Entscheid, die Vorgabe ist austauschbar.**
Wenn Joel bis Sonntag einen Schlüssel setzt, ist die SDK-Variante zwanzig Zeilen und
ändert an `judge.py` nichts. Die Signatur `str -> str` ist absichtlich das kleinste
gemeinsame Vielfache beider Wege — kein Nachrichtenformat, keine Rollen, kein
Anbieter-Objekt in der Signatur.

**3. Offline-Testbarkeit ist keine Bequemlichkeit, sondern die Regel.** Die
Zitatpflicht-Prüfung ist die inhaltlich wichtigste Logik der Schicht — sie muss in
Millisekunden und ohne Netz prüfbar sein, sonst wird sie nicht geprüft. Die fünf Tests
(gültiges Zitat · Zitat nicht im Kontext · Feld fehlt · Antwort kein JSON · Transport
wirft) sind alle Fake-Callables.

**4. Ein gescheiterter Aufruf ist keine Abwesenheit** (`verification.md`). Jeder Fehlweg —
Exit-Code ≠ 0, Timeout, kaputtes JSON, fehlendes Zitat, erfundenes Zitat — endet in
**derselben** Rückfall-Antwort mit `used_model: False` und einem `fallback_reason`, der
sagt, **welcher** Weg gescheitert ist. Das Register verliert dabei nichts: der
deterministische Befund stand vorher schon fest, das Modell durfte ihn nur gewichten.

**5. C wäre die billigste Option und kostet das teuerste Argument.** Fünf von sieben
simulierten Juroren fragten „wo ist der Agent?" (UEBERGABE §8). Schicht 2 ist der einzige
Ort, der darauf antwortet. Sie steht deshalb erst an Position 1 der Streichliste, nicht im
Plan schon gestrichen.

## Was der Vorgabe-Weg noch nicht belegt hat

Das genaue Ausgabeformat von `claude -p --output-format json` ist auf dieser Maschine
**nicht gemessen**. Der Plan enthält deshalb in P2 einen ausdrücklichen Messschritt, der
einmal aufruft und die tatsächliche Struktur in `harness/runs/judge-transport-probe.json`
festhält. Bis dahin gilt die Feldannahme `payload["result"]` als **unbelegt** und wird im
Code als solche markiert. Kein Feldname wandert ungemessen in Prosa.

## Was müsste passieren, damit es falsch war

- **`claude -p` verlangt ein interaktives Terminal** oder scheitert im Unterprozess. Dann
  fällt jeder Aufruf in den Rückfall, `used_model` ist überall `False`, und die Einreichung
  hätte einen Agenten, der nie läuft. Erkennbar sofort am Messschritt in P2 — nicht erst
  am Sonntag.
- **Die Laufzeit pro Kante liegt über ~10 s.** Bei 41 auffälligen Kanten wären das sieben
  Minuten für die Demo. Gegenmittel steht im Plan: das Urteil läuft nur über Kanten, die
  der deterministische Befund als auffällig markiert hat, mit `--judge-limit N` als harter
  Obergrenze, und die tatsächliche Dauer landet in `ledger.json` als
  `judge_seconds_total`.
- **Ein Schlüssel wird doch gesetzt und die SDK-Variante ist stabiler.** Dann ist der
  Entscheid nicht falsch, sondern die Vorgabe wechselt — genau dafür ist der Transport
  injizierbar. Falsch wäre er nur, wenn der Wechsel `judge.py` anfassen müsste.
