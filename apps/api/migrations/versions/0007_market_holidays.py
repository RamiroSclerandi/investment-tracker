"""market holidays

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRIVILEGES = ("SELECT", "INSERT", "UPDATE")
POLICY_CLAUSES = {
    "SELECT": "USING (true)",
    "INSERT": "WITH CHECK (true)",
    "UPDATE": "USING (true) WITH CHECK (true)",
}


def upgrade() -> None:
    op.execute("CREATE TYPE app.holiday_kind AS ENUM ('inamovible', 'trasladable', 'puente')")
    op.execute(
        """
        CREATE TABLE app.market_holidays (
            date date PRIMARY KEY,
            kind app.holiday_kind NOT NULL,
            name text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE app.market_holidays ENABLE ROW LEVEL SECURITY")
    op.execute("REVOKE ALL ON app.market_holidays FROM PUBLIC")
    op.execute(
        """
        DO $$
        DECLARE
            role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                    EXECUTE format('REVOKE ALL ON app.market_holidays FROM %I', role_name);
                END IF;
            END LOOP;
        END
        $$
        """
    )
    op.execute(f"GRANT {', '.join(PRIVILEGES)} ON app.market_holidays TO app_rw")
    for privilege in PRIVILEGES:
        op.execute(
            f"CREATE POLICY market_holidays_app_rw_{privilege.lower()} ON app.market_holidays"
            f" FOR {privilege} TO app_rw {POLICY_CLAUSES[privilege]}"
        )


def downgrade() -> None:
    op.execute("DROP TABLE app.market_holidays")
    op.execute("DROP TYPE app.holiday_kind")
