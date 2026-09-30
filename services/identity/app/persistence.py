"""Private database configuration and read-only schema readiness prerequisite."""
import os
from pathlib import Path
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import URL, create_engine
from sqlalchemy.pool import NullPool

SERVICE = "identity"
ROOT = Path(__file__).resolve().parents[1]


def config():
    return Config(str(ROOT / "alembic.ini"))


def engine():
    # Separate fields avoid URL interpolation/escaping and accidental DSN logging.
    host = os.environ.get("DB_HOST")
    secret = os.environ.get("DB_PASSWORD_FILE")
    if not host or not secret:
        raise ValueError("DB_HOST and DB_PASSWORD_FILE required")
    password = Path(secret).read_text().strip()
    if not password:
        raise ValueError("Empty database password")
    url = URL.create("postgresql+psycopg", username=SERVICE,
                     password=password, host=host,
                     port=int(os.environ.get("DB_PORT", "5432")), database=SERVICE)
    return create_engine(url, poolclass=NullPool, echo=False, hide_parameters=True,
                         connect_args={"connect_timeout": 3,
                                       "options": "-c statement_timeout=3000 -c lock_timeout=3000"})


_ENGINE = None


def get_engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = engine()
    return _ENGINE


def get_sessionmaker():
    from sqlalchemy.orm import sessionmaker
    return sessionmaker(autocommit=False, autoflush=False, bind=get_engine())


def get_db():
    maker = get_sessionmaker()
    db = maker()
    try:
        yield db
    finally:
        db.close()


def schema_ready():
    """Fail closed; no DDL. Group 4 must combine this with other dependencies."""
    db = None
    try:
        expected = set(ScriptDirectory.from_config(config()).get_heads())
        if len(expected) != 1:
            return False
        db = engine()
        with db.connect() as connection:
            actual = set(MigrationContext.configure(connection).get_current_heads())
        return actual == expected
    except Exception:
        # Do not expose DSN, credentials, query text or driver exceptions.
        return False
    finally:
        if db is not None:
            db.dispose()
