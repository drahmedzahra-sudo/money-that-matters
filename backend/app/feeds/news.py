import hashlib
import re
from urllib.parse import urlparse
import httpx
from .base import Feed, FeedResult
from ..services.relevance import MARKET_ALLOWED, EGYPT_ALLOWED, host_allowed, market_subject_ok, egypt_subject_ok
from ..services.dates import parse_date


def classify(text: str) -> str:
    t = text.lower()
    bullish = ["beats", "beat estimates", "raises guidance", "upgrade", "surge", "rises", "rally", "buyback", "approval", "record profit", "strong demand"]
    bearish = ["misses", "missed estimates", "cuts guidance", "downgrade", "falls", "slump", "lawsuit", "probe", "recall", "weak demand", "layoffs"]
    b = sum(1 for x in bullish if x in t)
    s = sum(1 for x in bearish if x in t)
    return "bullish" if b > s else "bearish" if s > b else "neutral"

class GdeltNewsFeed(Feed):
    def __init__(self, name: str, domains: list[str], egypt: bool = False):
        self.name, self.domains, self.egypt = name, domains, egypt

    async def fetch(self, tickers: dict[str, str] | None = None) -> FeedResult:
        allowed = EGYPT_ALLOWED if self.egypt else MARKET_ALLOWED
        items, errors = [], []
        tickers = tickers or {}
        domain_query = " OR ".join(f"domainis:{d}" for d in self.domains)
        query = f"({domain_query})"
        if self.egypt:
            query += " (Egypt OR EGX OR مصر OR البورصة)"
        else:
            # Search market terms, while the second-stage relevance gate remains authoritative.
            query += ' (earnings OR guidance OR stocks OR shares OR market OR rates OR tariff OR sector OR index)'
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                r = await client.get("https://api.gdeltproject.org/api/v2/doc/doc", params={"query": query, "mode": "artlist", "maxrecords": 250, "format": "json", "sort": "datedesc", "timespan": "24h"})
                r.raise_for_status()
                payload = r.json()
            for e in payload.get("articles", []):
                link = e.get("url", "")
                if not host_allowed(link, allowed): continue
                title = (e.get("title") or "").strip()
                if self.egypt:
                    if not egypt_subject_ok(title, native=False): continue
                    ticker = company = None
                else:
                    ticker, company = self._match_ticker(title, tickers)
                    if not market_subject_ok(title, ticker, company): continue
                published = e.get("seendate") or e.get("datetime") or ""
                try: dt = parse_date(published).isoformat()
                except Exception: continue
                items.append({"id": hashlib.sha256(link.encode()).hexdigest()[:20], "ticker": ticker, "company": company, "headline": title, "outlet": (urlparse(link).hostname or "").removeprefix("www."), "published_at": dt, "source_url": link, "lean": classify(title)})
            unique = {x["id"]: x for x in items}
            return FeedResult(list(unique.values()))
        except Exception as exc:
            return FeedResult([], str(exc))

    @staticmethod
    def _match_ticker(title: str, tickers: dict[str, str]):
        low = title.lower()
        for ticker, company in tickers.items():
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(ticker.lower())}(?![A-Za-z0-9])", low) or (company and company.lower() in low):
                return ticker, company
        return None, None
