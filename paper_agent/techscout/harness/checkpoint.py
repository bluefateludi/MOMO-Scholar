import sqlite3
from pathlib import Path
from types import TracebackType

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver


class SQLiteCheckpointAdapter:
    """Own the SQLite connection used by LangGraph checkpoint persistence."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._connection: sqlite3.Connection | None = None
        self._saver: SqliteSaver | None = None

    def __enter__(self) -> "SQLiteCheckpointAdapter":
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._path, check_same_thread=False)
        self._saver = SqliteSaver(
            self._connection,
            serde=JsonPlusSerializer(allowed_msgpack_modules=[]),
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._connection is not None:
            self._connection.close()
        self._connection = None
        self._saver = None

    @property
    def saver(self) -> SqliteSaver:
        if self._saver is None:
            raise RuntimeError("checkpoint adapter must be opened as a context manager")
        return self._saver
