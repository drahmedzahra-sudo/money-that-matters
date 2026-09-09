from abc import ABC, abstractmethod
from datetime import datetime, timezone

class FeedResult:
    def __init__(self, items=None, error=None):
        self.items = items or []
        self.error = error
        self.synced_at = datetime.now(timezone.utc)

class Feed(ABC):
    name: str
    @abstractmethod
    async def fetch(self):
        raise NotImplementedError
