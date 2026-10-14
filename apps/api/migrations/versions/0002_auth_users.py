"""auth users and email tokens

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    # Without WITH SCHEMA the extension lands in the first schema on search_path, which is
    # "app" itself when the role is named app; Supabase keeps extensions in "extensions".
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'extensions') THEN
                CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA extensions;
            ELSE
                CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA public;
            END IF;
        END
        $$
        """
    )
    op.execute("CREATE TYPE app.currency AS ENUM ('ARS', 'USD')")
    op.execute("CREATE TYPE app.email_token_purpose AS ENUM ('verify_email', 'reset_password')")
    op.execute(
        """
        CREATE TABLE app.users (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            email citext NOT NULL UNIQUE,
            password_hash text,
            email_verified_at timestamptz,
            display_name text NOT NULL,
            is_active boolean NOT NULL DEFAULT true,
            preferred_currency app.currency NOT NULL DEFAULT 'ARS',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("ALTER TABLE app.users ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE TABLE app.email_tokens (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id uuid NOT NULL REFERENCES app.users (id) ON DELETE CASCADE,
            purpose app.email_token_purpose NOT NULL,
            token_hash text NOT NULL UNIQUE,
            expires_at timestamptz NOT NULL,
            used_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX email_tokens_user_purpose_idx ON app.email_tokens (user_id, purpose)")
    op.execute("ALTER TABLE app.email_tokens ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP TABLE app.email_tokens")
    op.execute("DROP TABLE app.users")
    op.execute("DROP TYPE app.email_token_purpose")
    op.execute("DROP TYPE app.currency")
    op.execute("DROP SCHEMA app")
