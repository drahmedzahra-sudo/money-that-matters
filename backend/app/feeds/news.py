import asyncio, hashlib, random, re
from urllib.parse import urlparse
from email.utils import parsedate_to_datetime
import datetime as dtmod
import re as _re
import feedparser
import httpx
from .base import Feed, FeedResult
from .limiter import gdelt_limiter
from ..services.relevance import MARKET_ALLOWED, EGYPT_ALLOWED, host_allowed, market_subject_ok, egypt_subject_ok
from ..services.dates import parse_date

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

BULLISH = ["beats", "beat estimates", "raises guidance", "upgrade", "surge", "rises", "rally", "buyback", "approval", "record profit", "strong demand"]
BEARISH = ["misses", "missed estimates", "cuts guidance", "downgrade", "falls", "slump", "lawsuit", "probe", "recall", "weak demand", "layoffs"]

def classify(text: str) -> str:
    t = text.lower()
    b = sum(1 for x in BULLISH if x in t)
    s = sum(1 for x in BEARISH if x in t)
    return "bullish" if b > s else "bearish" if s > b else "neutral"

async def gdelt_get(client, params, attempts=4):
    for attempt in range(attempts):
        await gdelt_limiter.wait("api.gdeltproject.org")
        try:
            r = await client.get(GDELT_URL, params=params)
        except httpx.HTTPError:
            if attempt == attempts - 1: raise
            await asyncio.sleep(min(60, 2 ** attempt + random.random()))
            continue
        if r.status_code != 429:
            r.raise_for_status(); return r
        retry = r.headers.get("Retry-After")
        delay = None
        if retry:
            try: delay = max(0, float(retry))
            except ValueError:
                try: delay = max(0, (parsedate_to_datetime(retry) - dtmod.datetime.now(parsedate_to_datetime(retry).tzinfo)).total_seconds())
                except Exception: pass
        if delay is None: delay = min(90, 12 * (2 ** attempt)) + random.uniform(0, 2)
        if attempt == attempts - 1: r.raise_for_status()
        await asyncio.sleep(delay)
    raise RuntimeError("GDELT request failed")

class GdeltNewsFeed(Feed):
    def __init__(self, name, domains, egypt=False): self.name, self.domains, self.egypt = name, domains, egypt

    def _accept(self, link, title, tickers):
        allowed = EGYPT_ALLOWED if self.egypt else MARKET_ALLOWED
        if not host_allowed(link, allowed): return None
        if self.egypt:
            if not egypt_subject_ok(title, native=False): return None
            ticker = company = None
        else:
            ticker, company = self._match_ticker(title, tickers)
            if not market_subject_ok(title, ticker, company): return None
        return ticker, company

    def _convert(self, link, title, published, tickers):
        hit = self._accept(link, title, tickers)
        if hit is None: return None
        try: published = parse_date(published).isoformat()
        except Exception: return None
        return {"id": hashlib.sha256(link.encode()).hexdigest()[:20], "ticker": hit[0], "company": hit[1], "headline": title,
                "outlet": (urlparse(link).hostname or "").removeprefix("www."), "published_at": published,
                "source_url": link, "lean": classify(title)}

    async def fetch(self, tickers=None):
        tickers = tickers or {}
        domain_query = " OR ".join(f"domainis:{d.strip()}" for d in self.domains if d.strip())
        query = f"({domain_query})" + (" (Egypt OR EGX OR مصر OR البورصة)" if self.egypt else " (earnings OR guidance OR stocks OR shares OR market OR rates OR tariff OR sector OR index)")
        params = {"query": query, "mode": "artlist", "maxrecords": 100, "format": "json", "sort": "datedesc", "timespan": "24h"}
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                r = await gdelt_get(client, params)
                try:
                    payload = r.json()
                except ValueError:
                    # GDELT supports RSS for ArticleList; use it as a fallback when a JSON response is empty/non-JSON.
                    rss_params = dict(params); rss_params["format"] = "rss"
                    rr = await gdelt_get(client, rss_params)
                    parsed = feedparser.parse(rr.text)
                    entries = []
                    for e in parsed.entries:
                        link = getattr(e, "link", "")
                        title = (getattr(e, "title", "") or "").strip()
                        published = getattr(e, "published", "") or getattr(e, "updated", "")
                        item = self._convert(link, title, published, tickers)
                        if item: entries.append(item)
                    return FeedResult(list({x["id"]: x for x in entries}.values()))
            items=[]
            for e in payload.get("articles", []):
                link=e.get("url", ""); title=(e.get("title") or "").strip()
                item=self._convert(link,title,e.get("seendate") or e.get("datetime") or "",tickers)
                if item: items.append(item)
            return FeedResult(list({x["id"]: x for x in items}.values()))
        except Exception as exc:
            return FeedResult([], f"GDELT: {exc}")

    @staticmethod
    def _match_ticker(title, tickers):
        low=title.lower()
        for ticker, company in tickers.items():
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(ticker.lower())}(?![A-Za-z0-9])", low) or (company and company.lower() in low):
                return ticker, company
        return None, None

class MarketDirectFeed(Feed):
    """Allow-listed publisher RSS fallback when GDELT is rate-limited."""
    URLS=["https://www.cnbc.com/id/100003114/device/rss/rss.html"]
    async def fetch(self, tickers=None):
        tickers=tickers or {}
        items=[]
        headers={"User-Agent":"Money that matters/1.0"}
        try:
            async with httpx.AsyncClient(timeout=30,follow_redirects=True,headers=headers) as client:
                for url in self.URLS:
                    r=await client.get(url); r.raise_for_status()
                    parsed=feedparser.parse(r.text)
                    for e in parsed.entries:
                        link=getattr(e,"link",""); title=(getattr(e,"title","") or "").strip()
                        pub=getattr(e,"published","") or getattr(e,"updated","")
                        hit=self._match_ticker(title,tickers)
                        ticker,company=hit
                        if not host_allowed(link,MARKET_ALLOWED) or not market_subject_ok(title,ticker,company): continue
                        try: published=parse_date(pub).isoformat()
                        except Exception: continue
                        items.append({"id":hashlib.sha256(link.encode()).hexdigest()[:20],"ticker":ticker,"company":company,"headline":title,"outlet":(urlparse(link).hostname or "").removeprefix("www."),"published_at":published,"source_url":link,"lean":classify(title)})
                        if len(items)>=50: break
            return FeedResult(list({x["id"]:x for x in items}.values())) if items else FeedResult([],"Market direct RSS returned no verified records")
        except Exception as exc: return FeedResult([],f"Market direct: {exc}")
    @staticmethod
    def _match_ticker(title,tickers):
        low=title.lower()
        for ticker,company in tickers.items():
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(ticker.lower())}(?![A-Za-z0-9])",low) or (company and company.lower() in low): return ticker,company
        return None,None

class EgyptDirectFeed(Feed):
    """Direct, read-only Egypt business/news pages used when GDELT is unavailable."""
    URLS = [
        "https://english.ahram.org.eg/Category/3/14/Business/Markets--Companies.aspx",
    ]
    def __init__(self, name="egypt_news"): self.name=name

    async def fetch(self, tickers=None):
        import bs4
        items=[]
        headers={"User-Agent":"Money that matters/1.0"}
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as client:
                for url in self.URLS:
                    try:
                        r=await client.get(url); r.raise_for_status()
                    except Exception:
                        continue
                    soup=bs4.BeautifulSoup(r.text,"html.parser")
                    seen=set()
                    for a in soup.find_all("a", href=True):
                        title=" ".join(a.get_text(" ", strip=True).split())
                        href=a.get("href","")
                        if len(title)<20 or len(title)>240 or href in seen: continue
                        if not any(k in title.lower() for k in ["egypt","egx","stocks","market","company","investment","economy","bank","oil","energy","business","shares"]): continue
                        link=httpx.URL(url).join(href)
                        if not host_allowed(str(link), EGYPT_ALLOWED): continue
                        if not egypt_subject_ok(title, native=False): continue
                        seen.add(href)
                        raw_text=" ".join(a.parent.get_text(" ", strip=True).split())
                        m=_re.search(r"\b(?:0?[1-9]|[12]\d|3[01])/[01]?\d/20\d{2}\b", raw_text)
                        published=None
                        if m:
                            try: published=parse_date(m.group(0)).isoformat()
                            except Exception: published=None
                        items.append({"id":hashlib.sha256(str(link).encode()).hexdigest()[:20],"ticker":None,"company":None,"headline":title,"outlet":(urlparse(str(link)).hostname or "").removeprefix("www."),"published_at":published,"source_url":str(link),"lean":classify(title)})
                        if len(items)>=30: break
                    if len(items)>=30: break
            if not items: return FeedResult([], "Egypt direct sources returned no verified records")
            return FeedResult(list({x["id"]:x for x in items}.values()))
        except Exception as exc:
            return FeedResult([], f"Egypt direct: {exc}")
