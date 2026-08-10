# Das Demo-Video, weitgehend automatisch

Das Bild wird von Skripten hergestellt, der Ton nicht: **Joel spricht selbst,
nachtraeglich ueber das fertige stumme Bild.** Alles hier dient diesen zwei
Schritten.

Drehbuch: [`../video-script-final.md`](../video-script-final.md).
Sprechtext je Abschnitt und die Begruendung jeder Abweichung: [`segments.json`](segments.json).

## Ein Befehl

```
powershell -NoProfile -ExecutionPolicy Bypass -File docs/video/tools/record.ps1
```

Er prueft die Vorbedingungen, rendert die Endkarte, erzeugt die Mitschriften,
nimmt den ganzen Schnitt in **einem** Durchgang auf, stellt das Demo-Labor
wieder her, schneidet, legt zusammen, misst und zieht Kontrollbilder.

Danach den Ton drueberlegen:

```
powershell -NoProfile -ExecutionPolicy Bypass -File docs/video/tools/mux_voice.ps1 `
    -Voice "C:\Users\joel2\...\Aufnahme.m4a" -Offset 0.0
```

`-Offset` in Sekunden, mit Vorzeichen: **positiv** = der Ton kommt spaeter,
**negativ** = frueher. Der Windows-Sprachrekorder schreibt `.m4a`; ffmpeg liest
das direkt. Neu legen kostet Sekunden -- neu sprechen kostet Minuten.

## Was hier liegt

| Datei | Rolle |
|---|---|
| `segments.json` | Sprechtext je Abschnitt, Soll-Laenge, Bildinhalt, jede Abweichung vom Drehbuch mit Grund |
| `timing.json` | erzeugt: Soll gegen **gemessen** gegen Bildlaenge, plus Gesamtlaenge und Rest bis 3:00 |
| `transcripts/` | die **echte** Ausgabe der gezeigten Befehle, mit Rueckgabewert, Dauer, Zeitstempel |
| `audio/` | Referenzstimme je Abschnitt + `reference-track.wav` als Fuehrungsspur |
| `cuts/` | ein Video je Abschnitt -- einzeln austauschbar |
| `raw/` | Rohaufnahmen (`.mkv`) |
| `proof/` | Kontrollbilder zum **Ansehen**, bevor irgendetwas hochgeht |
| `tools/` | die Skripte |

`raw/`, `cuts/`, `proof/`, `audio/` und die fertigen `.mp4` sind
**gitignoriert** -- sie wuerden das Repo aufblaehen. Skripte, `segments.json`,
`timing.json` und die Mitschriften sind eingecheckt.

## Die Werkzeuge, in der Reihenfolge ihrer Verwendung

| Werkzeug | Was es tut |
|---|---|
| `reference_voice.ps1` | Referenzstimme je Abschnitt (Windows-Sprachausgabe, offline) |
| `plan_timing.py` | rechnet aus Soll **und Messung** die Laenge jedes Bildabschnitts |
| `reference_track.py` | legt die Referenzsaetze auf die Zeitachse -- Fuehrungsspur zum Mitsprechen |
| `endcard.py` | Endkarte, Repo-Adresse als **Parameter** |
| `transcripts.py` | fuehrt die gezeigten Befehle wirklich aus, legt die Ausgabe als Text ab |
| `capture.py` | Aufnahme -- **fenstergenau**, nie Desktop |
| `drive_console.py` | fuehrt den echten Mauszeiger durch den Schnitt, setzt die Marken |
| `assemble.py` | schneidet an den Marken, legt zusammen, misst |
| `proof_frames.py` | Kontrollbilder |
| `mux_voice.ps1` | Joels Tonspur drueber, mit Versatz |
| `record.ps1` | der eine Befehl, der alles davon in der richtigen Reihenfolge tut |

## Sieben Dinge, die gemessen wurden und den Dreh geaendert haben

Alle am 10.08.2026, alle mit einer Zahl statt einer Vermutung.

1. **Die Konsole braucht nach einem Knopfdruck 28-34 s, nicht 3.** Sie misst
   ihren ganzen sichtbaren Umfang neu (330 Fokusse). Vier Messungen: 27.96 /
   28.68 / 31.75 / 33.75 s. Die 2.896 s aus
   `harness/runs/warehouse-cut-latency.json`, auf die das Drehbuch baut, sind
   die **Katalog**-Seite. Der Schnitt wartet deshalb nicht auf die Konsole,
   sondern misst dieselbe Kante an der Kommandozeile neu: **1.25 s**, mit dem
   Zustand als Text im Bild.
2. **`gdigrab` sieht Chrome nur ohne DirectComposition.** Ohne
   `--disable-direct-composition` ist das Bild schwarz -- auch mit
   `--disable-gpu`. Lautlos, man merkt es erst am fertigen Video.
3. **Ein Konsolenfenster ist unter Windows 11 gar nicht aufnehmbar.** Derselbe
   Grund, und es gibt keinen Schalter dagegen. Deshalb laufen die Befehle
   wirklich und ihre **Ausgabe** wird als Textdatei im Browserfenster gezeigt.
4. **Der Nullpunkt der Aufnahme laesst sich am Anfang nicht bestimmen.** Am
   Dateiwachstum gemessen lag er **5.2 s** daneben. Der Versatz wird deshalb
   vom Ende her gerechnet.
5. **`SetForegroundWindow` scheitert still.** Eine 28-Sekunden-Testaufnahme
   zeigte das falsche Fenster, ohne Fehler.
6. **websocket-client braucht `suppress_origin=True`**, sonst lehnt Chrome
   jeden DevTools-Socket ab -- und der Fehler sieht aus wie "Port zu".
7. **Zeilennummer x Zeilenhoehe ist keine Scrollposition**, sobald Text
   umbricht. Der README-Schnitt stand auf dem falschen Abschnitt. Ein `Range`
   misst, wo der Text wirklich steht.

## Die Grenze

Aufnehmen, veroeffentlichen und einreichen macht Joel. Die Skripte bereiten
vor und messen; sie laden nichts hoch.
