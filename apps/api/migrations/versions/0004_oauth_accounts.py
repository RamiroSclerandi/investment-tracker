"""oauth accounts

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE TYPE app.oauth_provider AS ENUM ('google')")
    op.execute(
        """
        CREATE TABLE app.oauth_accounts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
            provider app.oauth_provider NOT NULL,
            provider_subject text NOT NULL,
            email text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT oauth_accounts_provider_subject_key UNIQUE (provider, provider_subject)
        )
        """
    )
    op.execute("CREATE INDEX oauth_accounts_user_id_idx ON app.oauth_accounts (user_id)")
    op.execute("ALTER TABLE app.oauth_accounts ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE app.oauth_accounts")
    op.execute("DROP TYPE app.oauth_provider")
