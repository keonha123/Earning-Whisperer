"""Shared MySQL connection pool; importing does not connect."""

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
import os
from ..config import load_project_env
from . import policies


load_project_env()


DB_URL = os.getenv("DB_URL", "mysql+pymysql://root:password@localhost:3306/graduate_project")


def engine_options(db_url: str) -> dict:
    """Bound MySQL network/pool waits, including sockets that stop responding.

    A connect timeout alone does not cover a stalled query or COMMIT. Keep
    driver-specific arguments out of SQLite and other test/database drivers.
    """
    options = {
        "pool_pre_ping": True,
        "pool_recycle": policies._env_int("DB_POOL_RECYCLE_SECONDS", 1800, minimum=30),
    }
    url = make_url(db_url)
    if url.get_backend_name() == "mysql" and url.get_driver_name() == "pymysql":
        options["pool_timeout"] = policies._env_int("DB_POOL_TIMEOUT_SECONDS", 5)
        options["connect_args"] = {
            "connect_timeout": policies._env_int("DB_CONNECT_TIMEOUT_SECONDS", 5),
            "read_timeout": policies._env_int("DB_READ_TIMEOUT_SECONDS", 5),
            "write_timeout": policies._env_int("DB_WRITE_TIMEOUT_SECONDS", 5),
        }
    return options


engine = create_engine(DB_URL, **engine_options(DB_URL))


def ping_database() -> None:
    """Raise when the configured database is not ready for scheduler work."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
