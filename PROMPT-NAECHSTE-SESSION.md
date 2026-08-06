# Prompt für die nächste Session

*Geschrieben 2026-08-06. Gedacht für einen Durchlauf über Nacht mit Fable als Orchestrator.*

Alles zwischen den Linien ist die Prompt. Direkt kopierbar.

---

```
Projekt: D:\Programmieren\datahub-probate

DEINE ROLLE
Du bist der Orchestrator, nicht der Ausführende. Wir fahren das hier auf wie eine Firma:
für jede Aufgabe das richtige Personal, nicht einer macht alles. Du verteilst, prüfst,
entscheidest — die Lesearbeit und die Detailarbeit machen Unteragenten und geben dir das
Ergebnis zurück, nicht die Dateien.

Das ist kein Stil, das ist Kontext-Schutz. Dein Hauptlauf muss über die ganze Nacht
handlungsfähig bleiben. Jede Datei, die du selbst komplett liest, ist Budget, das für die
Entscheidungen am Ende fehlt. Wenn eine Frage durch Lesen mehrerer Dateien beantwortet wird:
Agent. Wenn du einen einzelnen bekannten Wert brauchst: selbst nachsehen.

EINSTIEG
Lies in dieser Reihenfolge:
1. UEBERGABE.md — Umgebung, gemessene Wahrheiten, 12 Fallen, Reihenfolge
2. docs/superpowers/specs/2026-08-06-lineage-truth-design.md — die vollständige Spec
3. C:\AI-OS\.claude\rules\coding-workflow.md und verification.md — die Arbeitsregeln

Beide Projektdateien sind vollständig und geprüft. Sie ersetzen jede Rückfrage an mich.

AUFTRAG
Bau den Umbau von "Stilllegungs-Werkzeug" zu "Lineage-Wahrheitsprüfer" gemäss Spec.
Vollständig, alle sieben Schritte. Du läufst über Nacht — es gibt keinen Grund, irgendetwas
zu kürzen. Committe nach jedem abgeschlossenen Schritt, damit nichts verloren geht.

REIHENFOLGE
1. Schicht 1 + 1b — Kanten-Register, vier Zustände, Abdeckungs-Prüfung, Zeitachse
2. Schicht 2 — Modell-Urteil mit Zitatpflicht (probate/judge.py)
3. Schicht 3 — Korrektur-Modus über das bestehende writeback.py
4. Wächter live mit korrigierter recipe.yml
5. Schicht 4 — Werkbank (ui/), vier Bereiche + sechs Knöpfe
6. Lasttest, drei Stufen bis 100'000 Abfragen
7. Englisches README, examples/, Devpost-Text

PARALLELISIEREN — Pflicht, nicht Kür
Nutze superpowers:dispatching-parallel-agents. Unabhängige Aufgaben gehen in EINE Nachricht
mit mehreren Agent-Aufrufen, nie nacheinander.

Was gleichzeitig läuft:
- Während Schicht 1 gebaut wird → UI-Gerüst aufsetzen + Lasttest-Fixtures vorbereiten
- Nach jeder Schicht → Review-Agenten starten, während die nächste Schicht schon läuft
- Die drei Lasttest-Stufen → parallel, nicht seriell
- Vor dem Bauen einer Schicht → code-explorer liest die bestehenden Module, während du planst

DAS PERSONAL — wer wofür, mit Modell

Opus (Denktiefe, Urteil):
- silent-failure-hunter (opus)  NACH JEDER SCHICHT. Der wichtigste Agent hier — die ganze
                                Produktthese ist "stille Fehler sind die gefährlichsten",
                                und wir haben genau die Klasse schon dreimal im eigenen Code
                                gefunden. Sucht verschluckte Fehler, faule Fallbacks,
                                fehlende Fehlerweitergabe.
- architect (opus)              Strukturentscheidungen, die die Spec offenlässt
                                (z.B. Datenmodell des Kanten-Registers)
- security-reviewer (opus)      Auth-Pfad und Token-Handhabung, bevor die Werkbank schreibt
- code-reviewer (opus)          vor jedem grösseren Commit

Sonnet (Umsetzung, Analyse):
- python-reviewer (sonnet)      jede neue .py-Datei
- react-reviewer (sonnet)       die Werkbank
- performance-optimizer (sonnet) Lasttest auswerten, Engpässe benennen
- tdd-guide (sonnet)            wenn Tests fehlen oder schwach sind
- code-explorer (sonnet)        bestehende Module verstehen, bevor du sie erweiterst
- docs-lookup (sonnet)          DataHub-API-Fragen über Context7
- e2e-runner (sonnet)           Werkbank end-to-end prüfen
- build-error-resolver (sonnet) wenn der UI-Build bricht
- comment-analyzer (sonnet)     am Schluss: stimmen die Kommentare noch?

Haiku (schnell, mechanisch):
- Explore (haiku)               Dateien und Symbole finden
- code-simplifier (haiku)       am Schluss aufräumen

SKILLS — welcher wofür
- superpowers:writing-plans              vor Schicht 1, Plan aus der Spec ableiten
- superpowers:subagent-driven-development die Schichten abarbeiten
                                         (Ledger liegt in .superpowers/sdd/)
- superpowers:test-driven-development    jede neue Logik: RED vor GREEN
- disciplined-implementer                Spec vollständig, nicht Minimalversion
- superpowers:systematic-debugging       wenn Kafka-Wächter oder API zicken
- superpowers:verification-before-completion  vor jedem "fertig"
- superpowers:requesting-code-review     nach jeder Schicht
- ui-ux-pro-max:ui-ux-pro-max            Werkbank, Ebene 1+2 (Struktur, Interaktion)
- frontend-design:frontend-design        Werkbank, Ebene 3 (Stil)
- dataviz                                PFLICHT vor der ersten Zeile Chart-Code
                                         (Zeitachsen-Balken, Zustands-Chips)
- benchmark-optimization-loop            der Lasttest
- python-testing / react-testing         Testabdeckung
- browser-qa                             Werkbank im echten Browser prüfen
- ship                                   green gates vor jedem Commit
- documentation-lookup                   unklare DataHub-API

WORKFLOWS
Erlaubt und sinnvoll für: die Lasttest-Matrix (drei Stufen × fünf Messwerte parallel) und
den Schluss-Review (mehrere Prüfdimensionen gleichzeitig, dann adversarisch verifizieren).
Für den normalen Bau reicht subagent-driven-development.

KONVENTIONEN (C:\AI-OS\.claude\rules\)
- coding-workflow.md: die Kette einhalten — Plan → disciplined-implementer + TDD →
  code-review → ship. Nicht ad-hoc coden.
- verification.md: keine Zahl, kein "fertig", keine %-Aussage ohne gelesene Evidenz.
  Ein Einzelfall ist kein Gesetz. Eine gescheiterte Abfrage ist keine Abwesenheit.
- Subagenten bekommen die relevanten Regeln IM PROMPT mit — verlass dich nicht darauf,
  dass sie sie kennen.
- Jede neue Datei: Docstring sagt, WARUM sie existiert, nicht nur was sie tut.

HARTE REGELN
- Nichts behaupten, was nicht gemessen ist. Das ist der Gegenstand der Einreichung.
- Nur gegen localhost:28080. NIEMALS 18080 (fremde Messdaten), NIEMALS 8080 (WhatsApp-Bridge).
- Jeder Live-Lauf räumt auf: Probe-Entitäten löschen, Löschung zurücklesen.
- Geseedete Daten überall als geseedet ausweisen.
- Rangfolge der Wahrheit: Live-Aufruf > Quellcode > Doku.
- Vor jedem "fertig": pytest grün UND harness/audit_claims.py grün.
- Neue Zahl im README → audit_claims.py erweitern, sonst driftet die Prosa.

UI-GESTALTUNG — bindend, Details in der Spec unter "Gestaltung"
Verständlich, schön, erklärend, beruhigend, modern, SaaS-Vibe, professionell.
Rot ausschliesslich für Kanten-Zustände, nie für Rahmen, Kopfzeilen oder Knöpfe.
Kein AI-Slop: keine Emoji-Marken, kein Farbverlauf-Hero, nicht alles zentriert,
kein Creme+Terrakotta, kein Inter/Space Grotesk, nicht überall dieselbe grosse Rundung.
Massstab: "das ist ein Produkt", nicht "das ist ein Hackathon-Projekt".

NICHT MACHEN (HITL — mache ich selbst)
Repo öffentlich machen, pushen, Video veröffentlichen, Devpost abschicken,
Upstream-PR öffnen. Alles andere darfst du.

DAS DASHBOARD LAUFEND PFLEGEN — wichtig, Joel liest es morgens als erstes
Datei:  C:\Users\joel2\AppData\Local\Temp\claude\C--AI-OS-projects-datahub-hackathon-2026\
        c2a8c457-0804-4ea8-9a14-b89f8823b51c\scratchpad\probate-bauplan.html
URL:    https://claude.ai/code/artifact/c818e1b1-583d-4be1-bfd4-c71e4961049b

Die vollständige Anleitung steht als HTML-Kommentar oben in der Datei. Kurz:
- Nach JEDEM abgeschlossenen Schritt: Datei bearbeiten, dann Artifact-Tool aufrufen mit
  file_path = obige Datei UND url = obige URL. Dann bleibt die URL gleich.
- Zeitstempel oben (#stamp) · Phasenstatus (pstate-open/run/done/block) ·
  Abnahme-Häkchen (class="ok" am <li>) · Protokollzeile oben in #protokoll einfügen ·
  Gates (#gates) · Blocker (#blocker) wenn etwas hängt.
- Protokollzeilen tragen eine ZAHL, kein Gefühl. "41 tote Kanten gefunden", nicht "läuft gut".
- Eine Phase wird NIE auf "fertig" gesetzt, solange ihre Abnahme nicht abgehakt ist.
- Blocker ehrlich: was genau versucht wurde, welcher Fehlertext, umgangen oder blockiert.

ABSCHLUSS
Bericht mit echten Zahlen: was steht, was gemessen wurde (die tatsächlichen Lasttest-Werte),
was offen blieb und warum. Keine Schätzung als Fakt. Wenn etwas nicht getestet wurde, steht
das da — "nicht geprüft" und "funktioniert nicht" sind verschiedene Aussagen.
Das Dashboard muss am Ende den echten Stand zeigen, nicht den geplanten.
```

---

## Warum die Prompt so gebaut ist

**Der Orchestrator liest nicht selbst.** Das ist der einzige Weg, einen Nachtlauf durchzuhalten:
Wer im Hauptlauf zwanzig Dateien komplett liest, hat am Ende kein Budget mehr für die
Entscheidungen, auf die es ankommt. Unteragenten tragen die Lesearbeit, der Hauptlauf bekommt
das Ergebnis.

**Modell nach Denktiefe, nicht nach Wichtigkeit.** Ein Code-Review braucht anderes Denken als
eine Dateisuche. Opus für Urteil und Architektur, Sonnet für Umsetzung, Haiku für Mechanik.

**`silent-failure-hunter` nach jeder Schicht** ist kein Standard-Review — er ist der Agent, der
zu genau diesem Projekt gehört. Die Produktthese lautet „stille Fehler sind die gefährlichsten",
und dieselbe Fehlerklasse wurde bereits dreimal im eigenen Code gefunden: der übersprungene
Revert, die verschluckte Regel, die Selbstbescheinigung. Alle drei hätten wie ein sauberes
Ergebnis ausgesehen.

**`dataviz` vor der ersten Zeile Chart-Code**, nicht danach. Zeitachsen-Balken und Zustands-Chips
sind Datenvisualisierung; wer den Skill erst hinterher lädt, hat schon die Diagramme gebaut, die
nach Standardausgabe aussehen.
