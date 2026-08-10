# Referenz-Sprechspur (NICHT die Endspur).
#
# Joel spricht das Video selbst ein. Diese Spur existiert aus einem Grund:
# sie MISST, wie lange jeder Satz in echter Sprache dauert, damit das stumme
# Bild lang genug steht. Sie ist ausserdem der Rueckfall, falls seine Aufnahme
# scheitert.
#
# Warum die Windows-Sprachausgabe und nicht fal: der fal-Zugang antwortete am
# 10.08.2026 mit HTTP 403 "User is locked. Reason: Exhausted balance" auf jeden
# submit. Gemessen, nicht vermutet. Die Windows-Stimme ist offline, kostenlos
# und fuer eine Taktmessung genau genug.
#
# Aufruf:
#   powershell -NoProfile -ExecutionPolicy Bypass -File docs/video/tools/reference_voice.ps1
#   ... -Rate -2     (langsamer; -10..10, 0 = Standard)
#   ... -Voice "Microsoft Zira Desktop"

param(
  [string]$Voice = "Microsoft Hazel Desktop",
  [int]$Rate = -2,
  [string]$SegmentsJson = "docs/video/segments.json",
  [string]$OutDir = "docs/video/audio"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech

$root = (Get-Item $PSCommandPath).Directory.Parent.Parent.Parent.FullName
Set-Location $root

if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Force -Path $OutDir | Out-Null }

$data = Get-Content -Raw -Encoding UTF8 $SegmentsJson | ConvertFrom-Json

$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice($Voice)
$synth.Rate = $Rate

foreach ($seg in $data.segments) {
  if ([string]::IsNullOrWhiteSpace($seg.text)) {
    Write-Host ("skip  {0}  (silent segment)" -f $seg.id)
    continue
  }
  $out = Join-Path $OutDir ("{0}.wav" -f $seg.id)
  $synth.SetOutputToWaveFile($out)
  # Gedankenstriche spricht SAPI nicht als Pause -- durch Komma ersetzen,
  # sonst laeuft der Satz durch und die Messung ist zu kurz.
  $text = $seg.text -replace [char]0x2014, ","
  $synth.Speak($text)
  Write-Host ("wrote {0}" -f $out)
}
$synth.SetOutputToNull()
$synth.Dispose()
Write-Host "done."
