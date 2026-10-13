import json
from pathlib import Path

import pytest

from investment_tracker.cli import main


def test_export_openapi_writes_schema_without_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "openapi.json"

    exit_code = main(["export-openapi", "--output", str(output)])

    raw = output.read_text(encoding="utf-8")
    schema = json.loads(raw)
    assert exit_code == 0
    assert "/api/v1/healthz" in schema["paths"]
    assert "/api/v1/readyz" in schema["paths"]
    assert raw.endswith("}\n")
    assert raw == json.dumps(schema, indent=2, sort_keys=True) + "\n"
