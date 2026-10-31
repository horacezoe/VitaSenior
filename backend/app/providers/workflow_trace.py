"""Operational node metadata only: never record text, audio, images or keys."""
import json
import logging
import time

logger = logging.getLogger("vitasenior.workflow")
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.INFO)

def run_node(request_id, turn_id, node, call):
    started = time.monotonic()
    def emit(state, **extra):
        logger.info(json.dumps(dict(request_id=request_id, turn_id=turn_id,
            node=node, state=state, elapsed_ms=round((time.monotonic()-started)*1000), **extra)))
    emit("started")
    try:
        result = call()
    except Exception as error:
        emit("failed", code=getattr(error, "code", type(error).__name__))
        raise
    emit("succeeded")
    return result
