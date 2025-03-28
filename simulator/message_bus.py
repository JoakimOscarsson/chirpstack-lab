from typing import Callable, Awaitable, Any, List
import asyncio

class MessageBus:
    def __init__(self):
        self.subscribers: List[Callable[[Any], Awaitable[None]]] = []

    def subscribe(self, callback: Callable[[Any], Awaitable[None]]):
        self.subscribers.append(callback)

    async def publish(self, message: Any):
        for subscriber in self.subscribers:
            asyncio.create_task(subscriber(message))