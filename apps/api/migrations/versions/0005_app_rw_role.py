"""app_rw role, grants and policies

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_PRIVILEGES = {
    "users": ("SELECT", "INSERT", "UPDATE"),
    "email_tokens": ("SELECT", "INSERT", "UPDATE"),
    "refresh_tokens": ("SELECT", "INSERT", "UPDATE"),
    "oauth_accounts": ("SELECT", "INSERT"),
}
POLICY_CLAUSES = {
    "SELECT": "USING (true)",
    "INSERT": "WITH CHECK (true)",
    "UPDATE": "USING (true) WITH CHECK (true)",
}


def upgrade() -> None:
    # Login and password are set by the database owner outside migrations, never in git.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_rw') THEN
                CREATE ROLE app_rw NOLOGIN NOBYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE
                    NOINHERIT;
            END IF;
        END
        $$
        """
    )
    # The role is cluster-wide and may predate this migration with unsafe attributes.
    op.execute("ALTER ROLE app_rw NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT")
    _revoke_exposed_roles()
    op.execute("GRANT USAGE ON SCHEMA app TO app_rw")
    # Supabase installs citext in "extensions"; elsewhere it lives in "public".
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'extensions') THEN
                GRANT USAGE ON SCHEMA extensions TO app_rw;
                -- Without the grant option GRANT only warns, and citext would then fail at runtime.
                IF NOT has_schema_privilege('app_rw', 'extensions', 'USAGE') THEN
                    RAISE EXCEPTION 'app_rw did not receive USAGE on schema extensions'
                        USING HINT = 'Run the migration as a role that owns schema extensions'
                            ' or holds USAGE on it WITH GRANT OPTION, then retry.';
                END IF;
            END IF;
        END
        $$
        """
    )
    # Auth tables are reached before a user is known (register, login, verification, reset,
    # refresh, Google callback), so their policies cannot filter by user and allow every row.
    for table, privileges in TABLE_PRIVILEGES.items():
        op.execute(f"GRANT {', '.join(privileges)} ON app.{table} TO app_rw")
        for privilege in privileges:
            op.execute(
                f"CREATE POLICY {table}_app_rw_{privilege.lower()} ON app.{table}"
                f" FOR {privilege} TO app_rw {POLICY_CLAUSES[privilege]}"
            )


def _revoke_exposed_roles() -> None:
    op.execute("REVOKE ALL ON SCHEMA app FROM PUBLIC")
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA app FROM PUBLIC")
    # Supabase roles do not exist locally or in CI.
    op.execute(
        """
        DO $$
        DECLARE
            role_name text;
        BEGIN
            FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated', 'service_role'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                    EXECUTE format('REVOKE ALL ON SCHEMA app FROM %I', role_name);
                    EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA app FROM %I', role_name);
                    EXECUTE format(
                        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA app'
                        ' REVOKE ALL ON TABLES FROM %I', current_user, role_name);
                    EXECUTE format(
                        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA app'
                        ' REVOKE ALL ON SEQUENCES FROM %I', current_user, role_name);
                    EXECUTE format(
                        'ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA app'
                        ' REVOKE ALL ON FUNCTIONS FROM %I', current_user, role_name);
                END IF;
            END LOOP;
        END
        $$
        """
    )


def downgrade() -> None:
    for table, privileges in TABLE_PRIVILEGES.items():
        for privilege in privileges:
            op.execute(f"DROP POLICY {table}_app_rw_{privilege.lower()} ON app.{table}")
        op.execute(f"REVOKE ALL ON app.{table} FROM app_rw")
    op.execute("REVOKE ALL ON SCHEMA app FROM app_rw")
    # Revoked grants to PUBLIC and the Supabase roles stay revoked: restoring exposure is unsafe.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'extensions') THEN
                REVOKE USAGE ON SCHEMA extensions FROM app_rw;
            END IF;
        END
        $$
        """
    )
    # The role is cluster-wide: it stays while it owns or holds anything in another database.
    op.execute(
        """
        DO $$
        BEGIN
            DROP ROLE app_rw;
        EXCEPTION
            WHEN dependent_objects_still_exist THEN NULL;
        END
        $$
        """
    )
