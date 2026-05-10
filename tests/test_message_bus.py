import pytest

from core.message_bus import MessageBus
from core.message_types import Message, MessageType


@pytest.mark.asyncio
async def test_lower_priority_number_delivered_first() -> None:
    bus = MessageBus()
    bus.register("pm")
    await bus.publish(
        Message(
            type=MessageType.TASK_ASSIGN,
            sender="lead",
            recipient="pm",
            payload={"k": "later"},
            priority=5,
        )
    )
    await bus.publish(
        Message(
            type=MessageType.TASK_ASSIGN,
            sender="lead",
            recipient="pm",
            payload={"k": "first"},
            priority=1,
        )
    )
    a = await bus.receive("pm", timeout=2.0)
    b = await bus.receive("pm", timeout=2.0)
    assert a is not None and b is not None
    assert a.payload.get("k") == "first"
    assert b.payload.get("k") == "later"
