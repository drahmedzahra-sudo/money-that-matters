import asyncio, time
class HostLimiter:
    def __init__(self, min_interval: float): self.min_interval=min_interval; self._locks={}; self._last={}
    async def wait(self, host: str):
        lock=self._locks.get(host)
        if lock is None:
            lock=asyncio.Lock(); self._locks[host]=lock
        async with lock:
            now=time.monotonic(); delay=self.min_interval-(now-self._last.get(host,0))
            if delay>0: await asyncio.sleep(delay)
            self._last[host]=time.monotonic()
