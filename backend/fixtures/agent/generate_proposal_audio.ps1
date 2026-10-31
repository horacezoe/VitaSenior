# Preparation only. Runtime uses these exact pre-recorded WAVs on any OS.
# First run: python fixtures/agent/prepare_proposal_manifest.py (backend cwd).
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$manifestPath = Join-Path $PSScriptRoot 'proposal_manifest.json'
$samples = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voice.SelectVoice('Microsoft Huihui Desktop')
    $voice.Rate = 0
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    foreach ($sample in $samples) {
        $outputPath = Join-Path $PSScriptRoot $sample.file
        $voice.SetOutputToWaveFile($outputPath, $format)
        $voice.Speak($sample.text)
        $voice.SetOutputToNull()
        $sample | Add-Member -Force -NotePropertyName sha256 -NotePropertyValue ((Get-FileHash -LiteralPath $outputPath -Algorithm SHA256).Hash.ToLower())
        $sample | Add-Member -Force -NotePropertyName generated_by -NotePropertyValue 'Windows SAPI Microsoft Huihui Desktop; complete proposal text; offline 16kHz mono PCM'
    }
    $samples | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
} finally {
    $voice.Dispose()
}
