import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import SecretStr

from investment_tracker.core.settings import Settings
from investment_tracker.main import create_app

# The engine is only created in the lifespan, so this value is never used to connect.
_PLACEHOLDER_DATABASE_URL = SecretStr("postgresql+asyncpg://placeholder:placeholder@localhost/db")


def export_openapi(output: Path | None) -> None:
    app = create_app(Settings(database_url=_PLACEHOLDER_DATABASE_URL, environment="development"))
    document = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    if output is None:
        sys.stdout.write(document)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(document, encoding="utf-8", newline="\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_tracker.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export-openapi", help="Export the OpenAPI schema as JSON.")
    export.add_argument("--output", type=Path, default=None, help="Target file (default: stdout).")
    args = parser.parse_args(argv)
    export_openapi(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
