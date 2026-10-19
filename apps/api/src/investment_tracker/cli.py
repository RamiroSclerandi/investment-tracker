import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from pydantic import SecretStr

from investment_tracker.core.db import create_engine, create_sessionmaker
from investment_tracker.core.settings import Settings
from investment_tracker.main import create_app
from investment_tracker.market.catalog import SeedAsset, load_catalog
from investment_tracker.market.repository import UpsertCounts
from investment_tracker.market.seed import seed_assets

DEFAULT_CATALOG = Path("seed/assets.toml")

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


async def _seed_assets(assets: list[SeedAsset]) -> UpsertCounts:
    engine = create_engine(Settings())
    try:
        return await seed_assets(create_sessionmaker(engine), assets)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="investment_tracker.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export-openapi", help="Export the OpenAPI schema as JSON.")
    export.add_argument("--output", type=Path, default=None, help="Target file (default: stdout).")
    seed = commands.add_parser(
        "seed-assets", help="Insert or update the asset catalog from a TOML file (idempotent)."
    )
    seed.add_argument(
        "--file",
        type=Path,
        default=DEFAULT_CATALOG,
        help=f"Catalog file (default: {DEFAULT_CATALOG}).",
    )
    args = parser.parse_args(argv)
    if args.command == "seed-assets":
        counts = asyncio.run(_seed_assets(load_catalog(args.file.read_text(encoding="utf-8"))))
        sys.stdout.write(f"Seeded assets: {counts.inserted} inserted, {counts.updated} updated.\n")
        return 0
    export_openapi(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
