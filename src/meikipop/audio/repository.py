"""Read-only access to a Local Audio Server android.db database."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


class AudioRepositoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioClip:
    activation_id: int
    key: tuple[str, str]
    filename: str
    source: str
    data: bytes


class AudioRepository:
    REQUIRED = {
        "entries": {"id", "expression", "reading", "source", "file"},
        "android": {"id", "file", "source", "data"},
    }

    def __init__(self):
        self.connection: sqlite3.Connection | None = None
        self.path = ""

    def open(self, path: str):
        self.close()
        db_path = Path(path).expanduser()
        if not db_path.is_file():
            raise AudioRepositoryError(f"Audio database does not exist: {db_path}")
        uri = f"file:{quote(db_path.resolve().as_posix(), safe='/:')}?mode=ro"
        try:
            connection = sqlite3.connect(uri, uri=True)
            connection.execute("PRAGMA query_only=ON")
            self._validate(connection)
        except (sqlite3.Error, AudioRepositoryError) as exc:
            try:
                connection.close()
            except UnboundLocalError:
                pass
            raise AudioRepositoryError(str(exc)) from exc
        self.connection = connection
        self.path = str(db_path.resolve())

    def _validate(self, connection: sqlite3.Connection):
        for table, required_columns in self.REQUIRED.items():
            columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            missing = required_columns - columns
            if missing:
                raise AudioRepositoryError(
                    f"Invalid audio database: {table} is missing {', '.join(sorted(missing))}"
                )

    def close(self):
        if self.connection is not None:
            self.connection.close()
        self.connection = None
        self.path = ""

    def sources(self) -> list[str]:
        self._require_open()
        return [row[0] for row in self.connection.execute(
            "SELECT DISTINCT source FROM entries ORDER BY source"
        )]

    def load(self, activation_id: int, written_form: str, reading: str,
             preferred_sources: tuple[str, ...] = ()) -> AudioClip | None:
        self._require_open()
        rows = []
        if reading:
            rows.extend(self.connection.execute(
                "SELECT id, file, source FROM entries WHERE expression=? AND reading=?",
                (written_form, reading),
            ))
        else:
            # Keep all variants indexed and explicit: databases in the wild use
            # any of equal expression/reading, empty reading, or NULL reading.
            for sql, params in (
                ("SELECT id, file, source FROM entries WHERE expression=? AND reading=?", (written_form, written_form)),
                ("SELECT id, file, source FROM entries WHERE expression=? AND reading=''", (written_form,)),
                ("SELECT id, file, source FROM entries WHERE expression=? AND reading IS NULL", (written_form,)),
            ):
                rows.extend(self.connection.execute(sql, params))

        preference = {}
        for index, source in enumerate(preferred_sources):
            preference.setdefault(source, index)
        unique_rows = {row[0]: row for row in rows}.values()
        candidates = sorted(
            unique_rows,
            key=lambda row: (preference.get(row[2], len(preference)), row[2], row[0], row[1]),
        )
        key = (written_form, reading)
        for _entry_id, filename, source in candidates:
            audio_row = self.connection.execute(
                "SELECT data FROM android WHERE file=? AND source=? ORDER BY id LIMIT 1",
                (filename, source),
            ).fetchone()
            if audio_row is not None:
                return AudioClip(activation_id, key, filename, source, bytes(audio_row[0]))
        return None

    def _require_open(self):
        if self.connection is None:
            raise AudioRepositoryError("Audio repository is not open")
