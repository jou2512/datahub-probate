# Joels Tonaufnahme unter das stumme Bild legen.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File docs\video\tools\mux_voice.ps1 `
#       -Voice "C:\Users\joel2\...\Aufnahme.m4a" -Offset 0.0
#
# -Offset in Sekunden, mit Vorzeichen:
#   positiv  = der Ton kommt SPAETER (du hast zu frueh angefangen zu sprechen)
#   negativ  = der Ton kommt FRUEHER (du hast zu spaet angefangen)
# Ein halber Versuch reicht meist: einmal ansehen, Offset schaetzen, neu legen.
# Das kostet Sekunden - noch einmal sprechen kostet Minuten.
#
# Format: der Windows-Sprachrekorder ("Sprachrekorder" / "Voice Recorder")
# schreibt **.m4a** (AAC in MP4). ffmpeg liest das direkt, kein Umwandeln
# noetig. .wav, .mp3 und .ogg gehen genauso.
#
# Der Ton wird NICHT gestreckt. Ist er laenger als das Bild, sagt das Skript
# es und laesst das letzte Bild stehen (-Pad), statt heimlich abzuschneiden.

param(
  [Parameter(Mandatory = $true)][string]$Voice,
  [double]$Offset = 0.0,
  [string]$Silent = "docs\video\probate-demo-silent.mp4",
  [string]$Out    = "docs\video\probate-demo.mp4",
  [switch]$Pad,
  [int]$Gain = 0
)

$ErrorActionPreference = "Stop"
$root = (Get-Item $PSCommandPath).Directory.Parent.Parent.Parent.FullName
Set-Location $root

function Duration($f) {
  [double](ffprobe -v error -show_entries format=duration -of csv=p=0 $f)
}

if (-not (Test-Path $Voice))  { throw "Tonspur nicht gefunden: $Voice" }
if (-not (Test-Path $Silent)) { throw "Stummes Bild nicht gefunden: $Silent" }

$vid = Duration $Silent
$aud = Duration $Voice
Write-Host ("Bild  {0,7:N3} s" -f $vid)
Write-Host ("Ton   {0,7:N3} s  (Versatz {1:+0.000;-0.000;0.000} s)" -f $aud, $Offset)

$need = $aud + [Math]::Max(0.0, $Offset)
if ($need -gt $vid + 0.05) {
  $over = $need - $vid
  if ($Pad) {
    Write-Host ("  Ton ist {0:N2} s laenger - letztes Bild wird stehen gelassen." -f $over)
  } else {
    Write-Host ("  ACHTUNG: Ton ist {0:N2} s laenger als das Bild." -f $over)
    Write-Host "  Entweder -Pad setzen (letztes Bild bleibt stehen) oder schneller sprechen."
  }
}

# -itsoffset gilt fuer den NAECHSTEN Eingang, deshalb steht es vor -i $Voice.
# Negativer Versatz braucht zusaetzlich adelay/atrim; das erledigt hier
# `-af atrim` fuer den negativen Fall, damit ein Vorzeichen genuegt.
$args = @("-y","-hide_banner","-loglevel","error")
if ($Offset -ge 0) {
  $args += @("-i",$Silent,"-itsoffset","$Offset","-i",$Voice)
  $af = "aresample=async=1:first_pts=0"
} else {
  $args += @("-i",$Silent,"-i",$Voice)
  $af = "atrim=start=$([Math]::Abs($Offset)),asetpts=PTS-STARTPTS"
}
if ($Gain -ne 0) { $af += ",volume=${Gain}dB" }
# Sanfte Pegelfuehrung: kein Kompressor-Sound, nur ein Deckel gegen Spitzen.
$af += ",alimiter=limit=0.95"

$vf = if ($Pad) { @("-vf","tpad=stop_mode=clone:stop_duration=30") } else { @() }
$end = if ($Pad) { @("-shortest") } else { @("-shortest") }

$args += @("-map","0:v:0","-map","1:a:0","-af",$af) + $vf + @(
  "-c:v","libx264","-preset","slow","-crf","18","-pix_fmt","yuv420p",
  "-c:a","aac","-b:a","192k","-ar","48000","-movflags","+faststart") + $end + @($Out)

& ffmpeg @args
$final = Duration $Out
$mm = [int][Math]::Floor($final / 60); $ss = $final - ($mm * 60)
Write-Host ("`nFertig: {0}" -f $Out)
Write-Host ("GEMESSEN {0:N3} s = {1}:{2:00}   (Grenze 3:00, Rest {3:N2} s)" -f `
            $final, $mm, [int]$ss, (180.0 - $final))
if ($final -gt 180.0) { Write-Host "!! UEBER 3:00 - so nicht einreichen." }
