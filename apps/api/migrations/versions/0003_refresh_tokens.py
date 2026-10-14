"""refresh tokens

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app.refresh_tokens (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
            family_id uuid NOT NULL,
            token_hash text NOT NULL UNIQUE,
            expires_at timestamptz NOT NULL,
            rotated_at timestamptz,
            revoked_at timestamptz,
            user_agent text,
            ip text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX refresh_tokens_user_id_idx ON app.refresh_tokens (user_id)")
    op.execute("CREATE INDEX refresh_tokens_family_id_idx ON app.refresh_tokens (family_id)")
    op.execute("ALTER TABLE app.refresh_tokens ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE app.refresh_tokens")
