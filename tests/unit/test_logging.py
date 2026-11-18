import json
import logging

from rag.logging import JsonFormatter, configure_logging


def _format(record: logging.LogRecord) -> dict:
    return json.loads(JsonFormatter().format(record))


def test_extra_fields_are_included():
    record = logging.makeLogRecord(
        {
            "name": "rag.test",
            "levelname": "INFO",
            "msg": "hello %s",
            "args": ("world",),
            "law": "bgb",
        }
    )
    out = _format(record)
    assert out["msg"] == "hello world"
    assert out["law"] == "bgb"
    assert out["level"] == "INFO"
    assert "ts" in out


def test_exception_is_serialised():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.makeLogRecord({"msg": "failed", "exc_info": sys.exc_info()})
    assert "ValueError: boom" in _format(record)["exc"]


def test_configure_logging_writes_json(capsys):
    root = logging.getLogger()
    saved = root.handlers[:], root.level
    configure_logging("DEBUG")
    logging.getLogger("rag.x").info("ping", extra={"run_id": 3})
    line = capsys.readouterr().out.strip().splitlines()[-1]
    root.handlers[:], root.level = saved[0], saved[1]
    assert json.loads(line)["run_id"] == 3
