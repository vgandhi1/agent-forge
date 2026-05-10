import aiosqlite
import json
from typing import Any

from .paths import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_role  TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(agent_role, memory_type, key) ON CONFLICT REPLACE
);

CREATE TABLE IF NOT EXISTS message_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id  TEXT UNIQUE NOT NULL,
    type        TEXT NOT NULL,
    sender      TEXT NOT NULL,
    recipient   TEXT NOT NULL,
    payload     TEXT NOT NULL,
    timestamp   TEXT NOT NULL
);
"""


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA)
        await db.commit()


class AgentMemory:
    def __init__(self, agent_role: str) -> None:
        self.role = agent_role

    async def remember(self, key: str, value: Any, memory_type: str = "context") -> None:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO agent_memory (agent_role, memory_type, key, value) VALUES (?, ?, ?, ?)",
                (self.role, memory_type, key, json.dumps(value)),
            )
            await db.commit()

    async def recall(self, key: str, memory_type: str = "context") -> Any | None:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT value FROM agent_memory WHERE agent_role=? AND memory_type=? AND key=?",
                (self.role, memory_type, key),
            ) as cursor:
                row = await cursor.fetchone()
                return json.loads(row[0]) if row else None

    async def recall_all(self, memory_type: str = "context") -> dict[str, Any]:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT key, value FROM agent_memory WHERE agent_role=? AND memory_type=?",
                (self.role, memory_type),
            ) as cursor:
                rows = await cursor.fetchall()
                return {r[0]: json.loads(r[1]) for r in rows}

    async def recall_cross_role(self, other_role: str, key: str, memory_type: str = "artifact_ref") -> Any | None:
        """CEO can read other agents' artifact refs to load content for review."""
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT value FROM agent_memory WHERE agent_role=? AND memory_type=? AND key=?",
                (other_role, memory_type, key),
            ) as cursor:
                row = await cursor.fetchone()
                return json.loads(row[0]) if row else None
