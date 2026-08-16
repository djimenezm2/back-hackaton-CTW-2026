"""
Conversation state, kept in the database the rest of the system already uses.

A thread id is what turns a sequence of requests into a conversation: the second question
can say "and who can supply it" because the first one's answer is still there. Postgres
rather than memory, so it survives a restart and works with more than one worker — a
process-local checkpointer silently loses history the first time the app scales.

Note:
    The pool is separate from Django's ORM connections on purpose. LangGraph manages its
    own transactions around checkpoint writes, and sharing Django's connection would
    entangle those with whatever request transaction happens to be open.
"""

import threading

from django.conf import settings
from langgraph.checkpoint.base import BaseCheckpointSaver

_lock = threading.Lock()
_saver: BaseCheckpointSaver | None = None


def build_connection_string() -> str:
    """
    Build a libpq connection string from Django's own database settings.

    Returns:
        str: Points at the same database as the ORM. Deriving it rather than adding a
            second environment variable removes the chance of the two drifting apart and
            the agent quietly writing its history somewhere else.
    """
    db = settings.DATABASES["default"]
    return (
        f"postgresql://{db['USER']}:{db['PASSWORD']}"
        f"@{db['HOST']}:{db['PORT']}/{db['NAME']}?sslmode=prefer"
    )


def get_checkpointer() -> BaseCheckpointSaver:
    """
    The process-wide checkpointer, created once.

    Returns:
        BaseCheckpointSaver: A `PostgresSaver` with its tables already created.

    Note:
        Built lazily and under a lock. `setup()` issues DDL, so calling it from several
        threads at once races; doing it at import time would instead make every management
        command open a database connection it does not need.
    """
    global _saver
    if _saver is not None:
        return _saver

    with _lock:
        if _saver is None:
            from langgraph.checkpoint.postgres import PostgresSaver
            from psycopg import Connection
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            # `dict_row` and autocommit are what PostgresSaver expects of its connections
            pool: ConnectionPool[Connection] = ConnectionPool(
                conninfo=build_connection_string(),
                max_size=10,
                open=True,
                kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            )
            saver = PostgresSaver(pool)  # type: ignore[arg-type]  # row_factory set above
            saver.setup()
            _saver = saver
    return _saver
