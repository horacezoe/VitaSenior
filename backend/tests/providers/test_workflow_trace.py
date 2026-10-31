import pytest
from app.core.errors import AppError
from app.providers.workflow_trace import run_node

def test_trace_records_metadata_without_private_exception_message(caplog):
    error=AppError(502,'PROVIDER_ERROR','private transcript and credential')
    def fail():raise error
    with caplog.at_level('INFO',logger='vitasenior.workflow'):
        with pytest.raises(AppError) as exc:run_node('req-id','turn-id','understanding',fail)
    assert exc.value is error
    assert 'PROVIDER_ERROR' in caplog.text and 'req-id' in caplog.text
    assert 'private transcript' not in caplog.text and 'credential' not in caplog.text

def test_trace_preserves_success_value(caplog):
    result=object()
    with caplog.at_level('INFO',logger='vitasenior.workflow'):
        assert run_node('req-id','turn-id','asr',lambda:result) is result
    assert 'succeeded' in caplog.text
