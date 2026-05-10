import asyncio
import logging
from collections import defaultdict

from .memory import log_bus_message
from .message_types import Message

logger = logging.getLogger("agentforge.bus")


class MessageBus:
    """Priority-queue-based async message bus. Each agent role gets its own mailbox."""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.PriorityQueue] = defaultdict(asyncio.PriorityQueue)
        self._subscribers: set[str] = set()
        self._seq: int = 0

    def register(self, role: str) -> None:
        self._subscribers.add(role)
        _ = self._queues[role]  # ensure queue is created

    async def publish(self, message: Message) -> None:
        self._seq += 1
        # Tie-break on seq so heap ordering is stable (never compare Message objects)
        item = (message.priority, self._seq, message)
        await log_bus_message(message)
        logger.debug(
            "publish type=%s %s→%s id=%s",
            message.type.value,
            message.sender,
            message.recipient,
            message.message_id[:8],
        )
        if message.recipient == "broadcast":
            for role in self._subscribers:
                await self._queues[role].put(item)
        else:
            await self._queues[message.recipient].put(item)

    async def receive(self, recipient: str, timeout: float = 300.0) -> Message | None:
        try:
            _, _, message = await asyncio.wait_for(
                self._queues[recipient].get(), timeout=timeout
            )
            return message
        except asyncio.TimeoutError:
            return None

    def receive_nowait(self, recipient: str) -> Message | None:
        try:
            _, _, message = self._queues[recipient].get_nowait()
            return message
        except asyncio.QueueEmpty:
            return None
