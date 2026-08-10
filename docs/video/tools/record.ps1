# DER EINE BEFEHL. Nimmt das stumme Bild auf, schneidet es, legt es zusammen
# und raeumt das Demo-Labor wieder auf.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File docs/video/tools/record.ps1
#
# Was passiert, der Reihe nach:
#   1. Vorpruefung: GMS auf 28080, Konsole auf 8899, Labor in allen vier
#      Zustaenden. Schlaegt eine fehl, wird NICHT gedreht.
#   2. Endkarte rendern (Repo-Adresse als Parameter) und die Mitschriften
#      erzeugen -- die Befehle laufen dabei wirklich.
#   3. EINE Aufnahme: Chrome faehrt im Kiosk-Modus hoch, misst einmal (~30 s,
#      NOCH OHNE Kamera), dann laeuft die fenstergenaue Aufnahme und das
#      Skript klickt sich durch den ganzen Schnitt. Darin faellt der
#      `Disconnect`-Klick, und die Mitschrift zur gekappten Kante entsteht
#      waehrend des Halts.
#   4. AUFRAEUMEN: seed_lineage_lab.py, danach seedlab_verdicts.py (muss 0).
#   5. Schneiden, zusammenlegen, Endlaenge messen.
#   6. Sichtpruefung: Einzelbilder nach docs/video/proof/ -- ANSEHEN.
#
# AUFGENOMMEN WIRD NUR EIN FENSTER (`gdigrab -i title=...`), nie der Desktop.
# Auf diesem Rechner liegen Recherche ueber andere Teams, Slack und Mail
# offen -- eine Desktop-Aufnahme wuerde das mitveroeffentlichen.
#
# VORBEDINGUNGEN, die ein Mensch herstellt (das Skript kann sie nicht):
#   - Benachrichtigungen aus: Win+A -> "Nicht stoeren".
#   - Im Aufnahme-Chrome nur der Werkbank-Tab, keine Lesezeichenleiste.
#   - Waehrend der Aufnahme Maus und Tastatur NICHT anfassen. Das Skript
#     fuehrt den echten Mauszeiger.

param(
  [switch]$SkipPrerun,
  [string]$RepoUrl = "https://github.com/jou2512/datahub-probate"
)

$ErrorActionPreference = "Stop"
$root = (Get-Item $PSCommandPath).Directory.Parent.Parent.Parent.FullName
Set-Location $root
New-Item -ItemType Directory -Force -Path "docs/video/raw" | Out-Null

Write-Host "`n== 1. Vorpruefung =="
$code = curl.exe -s -o NUL -w "%{http_code}" http://localhost:28080/health
if ($code -ne "200") { throw "GMS antwortet nicht auf 28080 (gab '$code')" }
Write-Host "  GMS 28080: ok"
$code = curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:8899/werkbank.html
if ($code -ne "200") { throw "Konsole antwortet nicht auf 8899 (gab '$code')" }
Write-Host "  Konsole 8899: ok"
uv run --python 3.11 python harness/seedlab_verdicts.py | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Demo-Labor nicht in allen vier Zustaenden" }
Write-Host "  Demo-Labor: alle vier Zustaende, exit 0"
Write-Host "  Benachrichtigungen aus? Nur der Werkbank-Tab offen?" -ForegroundColor Yellow

Write-Host "`n== 2. Endkarte und Mitschriften =="
uv run --python 3.11 python docs/video/tools/endcard.py --repo-url $RepoUrl
uv run --python 3.11 python docs/video/tools/transcripts.py --which 06,07,07b

Write-Host "`n== 3. Aufnahme (ein Durchgang, ein Fenster) =="
$pre = if ($SkipPrerun) { @("--no-prerun") } else { @() }
uv run --python 3.11 --with websocket-client python docs/video/tools/drive_console.py `
    --take --keep-chrome --marks docs/video/marks-console.json `
    --record docs/video/raw/console.mkv @pre
if ($LASTEXITCODE -ne 0) { throw "Aufnahme fehlgeschlagen (exit $LASTEXITCODE)" }

Write-Host "`n== 4. Aufraeumen: Demo-Labor wiederherstellen =="
uv run --python 3.11 python harness/seed_lineage_lab.py | Select-Object -Last 1
uv run --python 3.11 python harness/seedlab_verdicts.py | Out-Null
if ($LASTEXITCODE -ne 0) { throw "seedlab_verdicts.py != 0 - das Labor ist NICHT wiederhergestellt" }
Write-Host "  seedlab_verdicts.py: exit 0"

Write-Host "`n== 5. Schneiden und zusammenlegen =="
uv run --python 3.11 python docs/video/tools/assemble.py
if ($LASTEXITCODE -ne 0) { throw "Zusammenlegen fehlgeschlagen" }

Write-Host "`n== 6. Sichtpruefung =="
uv run --python 3.11 python docs/video/tools/proof_frames.py

Write-Host "`nFertig. Stummes Bild: docs/video/probate-demo-silent.mp4"
Write-Host "Bilder zum Durchsehen: docs/video/proof/ - ANSEHEN, bevor irgendetwas hochgeht."
Write-Host "Ton daruebergelegt wird mit docs/video/tools/mux_voice.ps1."
