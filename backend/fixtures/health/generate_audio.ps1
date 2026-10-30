# Offline preparation of exact-text demo speech; never executed by the server.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$healthTemplates = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'templates.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$healthVoice = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $healthVoice.SelectVoice('Microsoft Huihui Desktop')
    $healthVoice.Rate = 0
    $healthManifest = @()
    foreach ($healthProperty in $healthTemplates.PSObject.Properties) {
        $healthSample = $healthProperty.Value
        $healthOutput = Join-Path $PSScriptRoot $healthSample.file
        $healthVoice.SetOutputToWaveFile($healthOutput)
        $healthVoice.Speak($healthSample.text)
        $healthVoice.SetOutputToNull()
        $healthManifest += @{
            template_id=$healthProperty.Name; file=$healthSample.file; text=$healthSample.text
            sha256=(Get-FileHash -LiteralPath $healthOutput -Algorithm SHA256).Hash.ToLower()
            is_mock=$true; generated_by='Windows SAPI Microsoft Huihui Desktop, fixed spoken text'
        }
    }
    $healthManifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'audio_manifest.json') -Encoding UTF8
} finally { $healthVoice.Dispose() }
