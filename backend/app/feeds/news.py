import asyncio, hashlib, random, re
from urllib.parse import urlparse
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET
import httpx
from .base import Feed, FeedResult
from .limiter import gdelt_limiter
from ..services.relevance import MARKET_ALLOWED, EGYPT_ALLOWED, host_allowed, market_subject_ok, egypt_subject_ok
from ..services.dates import parse_date

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

def classify(text: str) -> str:
    t = text.lower()
    bullish = ["beats", "beat estimates", "raises guidance", "upgrade", "surge", "rises", "rally", "buyback", "approval", "record profit", "strong demand"]
    bearish = ["misses", "missed estimates", "cuts guidance", "downgrade", "falls", "slump", "lawsuit", "probe", "recall", "weak demand", "layoffs"]
    b, s = sum(x in t for x in bullish), sum(x in t for x in bearish)
    return "bullish" if b > s else "bearish" if s > b else "neutral"

async def gdelt_get(client, params, attempts=4):
    last_error = None
    for attempt in range(attempts):
        await gdelt_limiter.wait("api.gdeltproject.org")
        try:
            response = await client.get(GDELT_URL, params=params)
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt == attempts - 1: raise
            await asyncio.sleep(min(60.0, 2.0 ** attempt + random.random()))
            continue
        if response.status_code != 429:
            response.raise_for_status(); return response
        retry_after = response.headers.get("Retry-After")
        delay = None
        if retry_after:
            try: delay = max(0.0, float(retry_after))
            except ValueError:
                try:
                    dt = parsedate_to_datetime(retry_after)
                    delay = max(0.0, (dt - __import__('datetime').datetime.now(dt.tzinfo)).total_seconds())
                except Exception: pass
        if delay is None: delay = min(60.0, 10.0 * (2 ** attempt)) + random.uniform(0, 2)
        if attempt == attempts - 1: response.raise_for_status()
        await asyncio.sleep(delay)
    raise last_error or RuntimeError("GDELT request failed without a response")

def parse_gdelt_payload(response):
    text = response.text.lstrip('\ufeff').strip()
    if not text: raise ValueError("GDELT returned an empty response")
    try: return response.json()
    except ValueError:
        # Some GDELT paths can return a JSON-looking body with a wrong content type.
        import json
        try: return json.loads(text)
        except ValueError as exc: raise ValueError(f"GDELT returned non-JSON content: {text[:120]!r}") from exc

class GdeltNewsFeed(Feed):
    def __init__(self, name, domains, egypt=False): self.name, self.domains, self.egypt = name, domains, egypt
    async def fetch(self, tickers=None):
        allowed = EGYPT_ALLOWED if self.egypt else MARKET_ALLOWED
        items=[]; tickers=tickers or {}
        domain_query = " OR ".join(f"domainis:{d.strip()}" for d in self.domains if d.strip())
        query = f"({domain_query})" + (" (Egypt OR EGX OR مصر OR البورصة)" if self.egypt else ' (earnings OR guidance OR stocks OR shares OR market OR rates OR tariff OR sector OR index)')
        params={"query":query,"mode":"artlist","maxrecords":250,"format":"json","sort":"datedesc","timespan":"24h"}
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                r=await gdelt_get(client, params)
                payload=parse_gdelt_payload(r)
            for e in payload.get("articles",[]):
                link=e.get("url","")
                if not host_allowed(link, allowed): continue
                title=(e.get("title") or "").strip()
                if self.egypt:
                    if not egypt_subject_ok(title, native=False): continue
                    ticker=company=None
                else:
                    ticker,company=self._match_ticker(title,tickers)
                    if not market_subject_ok(title,ticker,company): continue
                try: dt=parse_date(e.get("seendate") or e.get("datetime") or "").isoformat()
                except Exception: continue
                items.append({"id":hashlib.sha256(link.encode()).hexdigest()[:20],"ticker":ticker,"company":company,"headline":title,"outlet":(urlparse(link).hostname or "").removeprefix("www."),"published_at":dt,"source_url":link,"lean":classify(title)})
            unique={x["id"]:x for x in items}
            return FeedResult(list(unique.values()))
        except Exception as exc:
            return FeedResult([], f"GDELT: {exc}")
    @staticmethod
    def _match_ticker(title,tickers):
        low=title.lower()
        for ticker,company in tickers.items():
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(ticker.lower())}(?![A-Za-z0-9])",low) or (company and company.lower() in low): return ticker,company
        return None,None
