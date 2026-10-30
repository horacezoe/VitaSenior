# Recreate genuine fixed Chinese speech on Windows with the installed SAPI voice.
# This script is fixture preparation only; the server does not depend on SAPI.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$outputDirectory = $PSScriptRoot
$voice = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $voice.SelectVoice('Microsoft Huihui Desktop')
    $voice.Rate = 0
    $samples = @(
        @{fixture_id='exercise_walk'; file='exercise_input.wav'; text='我散步了20分钟。'},
        @{fixture_id='exercise_reply'; file='exercise_reply.wav'; text='【模拟】要记下这次散步20分钟吗？'},
        @{fixture_id='preference_reply'; file='preference_reply.wav'; text='【模拟】我会记住这条明确表达的偏好。'},
        @{fixture_id='greeting'; file='greeting.wav'; text='您好'},
        @{fixture_id='proposal_change_example'; file='proposal_change_example.wav'; text='【模拟】孩子申请将医疗备注修改为“补充社区复查记录”。如不同意，请明确拒绝。'}
    )
    foreach ($sample in $samples) {
        $voice.SetOutputToWaveFile((Join-Path $outputDirectory $sample.file))
        $voice.Speak($sample.text)
        $voice.SetOutputToNull()
        $sample['sha256'] = (Get-FileHash -LiteralPath (Join-Path $outputDirectory $sample.file) -Algorithm SHA256).Hash.ToLower()
        $sample['generated_by'] = 'Windows SAPI Microsoft Huihui Desktop; offline fixed spoken content'
    }
    $samples | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $outputDirectory 'audio_manifest.json') -Encoding UTF8
} finally {
    $voice.Dispose()
}
