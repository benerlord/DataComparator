import json
from pathlib import Path
from datacompare.utils.logging import configure_logging, get_logger


def test_configure_and_log_json_file(tmp_path):
    log_file = tmp_path / "app.log"
    configure_logging(level="INFO", log_file=log_file)
    logger = get_logger("test")
    logger.info("engine_selected", engine="memory", rows=1000)
    contents = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(contents) >= 1
    payload = json.loads(contents[-1])
    assert payload["event"] == "engine_selected"
    assert payload["engine"] == "memory"
    assert payload["rows"] == 1000
