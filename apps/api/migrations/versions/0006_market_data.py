"""market data and job runs

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMPS = """
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
"""
TABLES = {
    "assets": f"""
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        type app.asset_type NOT NULL,
        symbol text NOT NULL,
        name text NOT NULL,
        quote_currency app.currency NOT NULL,
        price_factor numeric(30, 10) NOT NULL DEFAULT 1 CHECK (price_factor > 0),
        maturity_date date,
        fci_category text,
        provider text NOT NULL,
        provider_ref text NOT NULL,
        live_provider text,
        is_tracked boolean NOT NULL DEFAULT false,
        {TIMESTAMPS},
        CONSTRAINT assets_provider_provider_ref_key UNIQUE (provider, provider_ref)
    """,
    "latest_prices": f"""
        asset_id uuid PRIMARY KEY REFERENCES app.assets (id),
        price numeric(30, 10) NOT NULL,
        ts timestamptz NOT NULL,
        source text NOT NULL,
        {TIMESTAMPS}
    """,
    "asset_prices": f"""
        asset_id uuid NOT NULL REFERENCES app.assets (id),
        bucket timestamptz NOT NULL,
        price numeric(30, 10) NOT NULL,
        source text NOT NULL,
        {TIMESTAMPS},
        PRIMARY KEY (asset_id, bucket),
        CONSTRAINT asset_prices_bucket_on_the_hour
            CHECK (date_trunc('hour', bucket AT TIME ZONE 'UTC') = bucket AT TIME ZONE 'UTC')
    """,
    "asset_prices_daily": f"""
        asset_id uuid NOT NULL REFERENCES app.assets (id),
        date date NOT NULL,
        close numeric(30, 10) NOT NULL,
        source text NOT NULL,
        {TIMESTAMPS},
        PRIMARY KEY (asset_id, date)
    """,
    "fx_rates": f"""
        rate_type app.fx_rate_type NOT NULL,
        ts timestamptz NOT NULL,
        buy numeric(20, 6) NOT NULL,
        sell numeric(20, 6) NOT NULL,
        mid numeric(20, 6) GENERATED ALWAYS AS ((buy + sell) / 2) STORED,
        {TIMESTAMPS},
        PRIMARY KEY (rate_type, ts)
    """,
    "fx_rates_daily": f"""
        rate_type app.fx_rate_type NOT NULL,
        date date NOT NULL,
        buy numeric(20, 6) NOT NULL,
        sell numeric(20, 6) NOT NULL,
        mid numeric(20, 6) GENERATED ALWAYS AS ((buy + sell) / 2) STORED,
        {TIMESTAMPS},
        PRIMARY KEY (rate_type, date)
    """,
    "fx_latest": f"""
        rate_type app.fx_rate_type PRIMARY KEY,
        buy numeric(20, 6) NOT NULL,
        sell numeric(20, 6) NOT NULL,
        mid numeric(20, 6) GENERATED ALWAYS AS ((buy + sell) / 2) STORED,
        ts timestamptz NOT NULL,
        {TIMESTAMPS}
    """,
    "job_runs": f"""
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        job text NOT NULL,
        started_at timestamptz NOT NULL,
        finished_at timestamptz,
        status app.job_run_status NOT NULL,
        items_ok integer NOT NULL DEFAULT 0,
        items_failed integer NOT NULL DEFAULT 0,
        error text,
        meta jsonb NOT NULL DEFAULT '{{}}'::jsonb,
        {TIMESTAMPS}
    """,
}
# Retention downsamples hour buckets, so only the bucketed tables need DELETE.
TABLE_PRIVILEGES = {
    "assets": ("SELECT", "INSERT", "UPDATE"),
    "latest_prices": ("SELECT", "INSERT", "UPDATE"),
    "asset_prices": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "asset_prices_daily": ("SELECT", "INSERT", "UPDATE"),
    "fx_rates": ("SELECT", "INSERT", "UPDATE", "DELETE"),
    "fx_rates_daily": ("SELECT", "INSERT", "UPDATE"),
    "fx_latest": ("SELECT", "INSERT", "UPDATE"),
    "job_runs": ("SELECT", "INSERT", "UPDATE"),
}
POLICY_CLAUSES = {
    "SELECT": "USING (true)",
    "INSERT": "WITH CHECK (true)",
    "UPDATE": "USING (true) WITH CHECK (true)",
    "DELETE": "USING (true)",
}
ENUM_TYPES = {
    "asset_type": (
        "CRYPTO",
        "STOCK_AR",
        "STOCK_US",
        "CEDEAR",
        "SOV_BONDS",
        "FIXED_RATE_AR",
        "CORP_BONDS",
        "MUTUAL_FUNDS",
    ),
    "fx_rate_type": ("MEP",),
    "job_run_status": ("OK", "PARTIAL", "FAILED", "SKIPPED_LOCKED", "NOT_DUE"),
}


def upgrade() -> None:
    for name, values in ENUM_TYPES.items():
        labels = ", ".join(f"'{value}'" for value in values)
        op.execute(f"CREATE TYPE app.{name} AS ENUM ({labels})")
    for table, columns in TABLES.items():
        op.execute(f"CREATE TABLE app.{table} ({columns})")
        op.execute(f"ALTER TABLE app.{table} ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE INDEX job_runs_job_started_at_idx ON app.job_runs (job, started_at DESC)")
    _revoke_exposed_roles()
    # Market data is shared by every user, so the policies cannot filter rows.
    for table, privileges in TABLE_PRIVILEGES.items():
        op.execute(f"GRANT {', '.join(privileges)} ON app.{table} TO app_rw")
        for privilege in privileges:
            op.execute(
                f"CREATE POLICY {table}_app_rw_{privilege.lower()} ON app.{table}"
                f" FOR {privilege} TO app_rw {POLICY_CLAUSES[privilege]}"
            )


def _revoke_exposed_roles() -> None:
    # Supabase's global default privileges grant new tables to its API roles at creation.
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA app FROM PUBLIC")
    op.execute(
        """
        DO $$
        DECLARE
            role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                    EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA app FROM %I', role_name);
                END IF;
            END LOOP;
        END
        $$
        """
    )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE app.{table}")
    for name in reversed(ENUM_TYPES):
        op.execute(f"DROP TYPE app.{name}")
