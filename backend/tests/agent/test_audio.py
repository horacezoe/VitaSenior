import hashlib
import json
from pathlib import Path

import pytest

from app.core.errors import AppError
from app.providers.mock_audio import FIXTURES, MockASR, MockTTS, inspect_wav


def catalog():
    return json.loads((FIXTURES/'audio_manifest.json').read_text(encoding='utf-8-sig'))


def test_fixed_chinese_speech_is_real_pcm_and_exact_text_only():
    for row in catalog():
        raw=(FIXTURES/row['file']).read_bytes()
        assert raw[:4]==b'RIFF' and raw[8:12]==b'WAVE'
        assert hashlib.sha256(raw).hexdigest()==row['sha256']
        assert 300 < inspect_wav(raw) < 60000
        output=MockTTS().synthesize(row['text'])
        assert output.content==raw and output.is_mock and output.text==row['text']
        recognized=MockASR().transcribe(raw,'audio/wav',row['fixture_id'])
        assert recognized.transcript==row['text'] and recognized.is_mock and recognized.provider=='mock'


def test_unknown_text_or_audio_does_not_get_fake_speech_or_transcript():
    with pytest.raises(AppError) as exc:MockTTS().synthesize('这段任意新文本没有对应的真实录音')
    assert exc.value.status==501
    row=catalog()[0]
    audio=bytearray((FIXTURES/row['file']).read_bytes())
    audio[-2] ^= 1  # Still genuine WAV, but no longer this known recording.
    with pytest.raises(AppError) as exc:MockASR().transcribe(bytes(audio),'audio/wav')
    assert exc.value.status==422


@pytest.mark.parametrize('raw,mime',[(b'not-a-wave','audio/wav'),(b'RIFF','audio/wav'),(b'not-mp3','audio/mpeg')])
def test_actual_encoding_must_match_the_claim(raw,mime):
    with pytest.raises(AppError) as exc:MockASR().transcribe(raw,mime)
    assert exc.value.code=='ASR_FORMAT_UNSUPPORTED'
