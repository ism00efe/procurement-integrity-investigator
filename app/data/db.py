from pathlib import Path

import duckdb

from app.core.config import get_settings


def get_connection(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    settings = get_settings()
    path = Path(settings.duckdb_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path), read_only=read_only)
