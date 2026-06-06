from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import uuid
from datetime import UTC, datetime


class MessageType(str, Enum):
    TASK_ASSIGN = "task_assign"
    TASK_COMPLETE = "task_complete"
    TASK_BLOCKED = "task_blocked"
    ARTIFACT_APPROVED = "artifact_approved"
    ARTIFACT_REJECTED = "artifact_rejected"
    CONSULT_REQUEST = "consult_request"
    CONSULT_RESPONSE = "consult_response"
    ESCALATION = "escalation"
    SHUTDOWN = "shutdown"


@dataclass
class Message:
    type: MessageType
    sender: str
    recipient: str
    payload: dict
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    priority: int = 5

    def __lt__(self, other: "Message") -> bool:
        return self.priority < other.priority
