"""Baseline: the schema in docker/postgres/init.

Docker Compose creates the schema from those SQL files when the database volume is first made.
This migration applies the same files to an empty database, so `alembic upgrade head` gives the
same result outside Docker. A database that already has the schema is only stamped.
"""

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "3b27e5426523"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docker" / "postgres" / "init"


def split_statements(sql: str) -> list[str]:
    """Split a SQL script on semicolons outside $$-quoted function bodies and comments."""
    statements, current, in_dollar = [], [], False
    for line in sql.splitlines():
        # Trailing "-- comment" text is dropped; the schema has no "--" inside string literals.
        code = line if in_dollar else line.split("--", 1)[0]
        if not code.strip():
            continue
        current.append(code)
        if code.count("$$") % 2 == 1:
            in_dollar = not in_dollar
        if not in_dollar and code.rstrip().endswith(";"):
            statement = "\n".join(current).strip()
            # Alembic runs the migration in its own transaction.
            if statement.rstrip(";").strip().upper() not in ("", "BEGIN", "COMMIT"):
                statements.append(statement)
            current = []
    if "\n".join(current).strip():
        statements.append("\n".join(current).strip())
    return statements


def upgrade() -> None:
    bind = op.get_bind()
    if bind.exec_driver_sql("SELECT to_regclass('public.agents')").scalar() is not None:
        return
    for sql_file in sorted(SCHEMA_DIR.glob("*.sql")):
        for statement in split_statements(sql_file.read_text(encoding="utf-8")):
            bind.exec_driver_sql(statement)


def downgrade() -> None:
    raise NotImplementedError("The baseline schema cannot be downgraded; drop the database.")
