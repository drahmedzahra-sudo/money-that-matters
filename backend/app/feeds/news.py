import asyncio, hashlib, random, re
from urllib.parse import urlparse
from email.utils import parsedate_to_datetime
import datetime as dtmod
import re as _re
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

async def gdelt_get(client, params, attempts=1):
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
        if self.egypt:
            # Keep the GDELT query compact. A long OR-list can be rejected by
            # GDELT before it even reaches the rate limiter. Direct Egypt
            # publishers are preferred by sync_all; this is only an index fallback.
            egypt_domains = [d.strip() for d in self.domains if d.strip()][:4]
            domain_query = " OR ".join(f"domainis:{d}" for d in egypt_domains)
            query = f"({domain_query}) Egypt" if domain_query else "Egypt"
        else:
            domain_query = " OR ".join(f"domainis:{d.strip()}" for d in self.domains if d.strip())
            query = f"({domain_query}) (earnings OR guidance OR stocks OR shares OR market OR rates OR tariff OR sector OR index)"
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
                    import feedparser
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
                    import feedparser
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

class EgyptEGXFeed(Feed):
    """Official Egyptian Exchange disclosures/news from the public EGX homepage."""
    URL = "https://beta.egx.com.eg/en"
    def __init__(self, name="egypt_news"): self.name=name

    @staticmethod
    def _published_from_context(text):
        # EGX displays month/day on the live homepage. The page itself is the
        # current-year source, so attaching the current UTC year is defensible.
        m=re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\b", text, re.I)
        if not m: return None
        try:
            year=dtmod.datetime.now(dtmod.timezone.utc).year
            return dtmod.datetime.strptime(f"{m.group(1)} {m.group(2)} {year}", "%b %d %Y").replace(tzinfo=dtmod.timezone.utc).isoformat()
        except Exception: return None

    async def fetch(self, tickers=None):
        import bs4
        items=[]
        headers={"User-Agent":"Money that matters/1.0"}
        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=headers) as client:
                r=await client.get(self.URL); r.raise_for_status()
            soup=bs4.BeautifulSoup(r.text,"html.parser")
            seen=set()
            for a in soup.find_all("a", href=True):
                href=a.get("href","")
                if not re.search(r"/news/\d+", href, re.I): continue
                title=" ".join(a.get_text(" ",strip=True).split())
                if len(title)<15 or title in seen: continue
                link=str(httpx.URL(self.URL).join(href))
                if not host_allowed(link,{"beta.egx.com.eg","egx.com.eg"}): continue
                context=""
                node=a
                for _ in range(4):
                    node=getattr(node,"parent",None)
                    if not node: break
                    candidate=" ".join(node.get_text(" ",strip=True).split())
                    if self._published_from_context(candidate):
                        context=candidate
                        break
                if not context:
                    context=" ".join(a.get_text(" ",strip=True).split())
                published=self._published_from_context(context)
                if not published: continue
                code_match=re.search(r"\b([A-Z0-9]{2,8}\.CA)\b", context)
                ticker=code_match.group(1) if code_match else None
                company=None
                if code_match:
                    before=context[:code_match.start()].strip(" -–—")
                    if before and len(before)<160: company=before
                items.append({
                    "id":hashlib.sha256(link.encode()).hexdigest()[:20],
                    "ticker":ticker,
                    "company":company,
                    "headline":title,
                    "outlet":"egx.com.eg",
                    "published_at":published,
                    "source_url":link,
                    "lean":classify(title),
                })
                seen.add(title)
                if len(items)>=40: break
            return FeedResult(list({x["id"]:x for x in items}.values())) if items else FeedResult([],"EGX returned no verified news records")
        except Exception as exc:
            return FeedResult([],f"EGX: {exc}")

class EgyptDirectFeed(Feed):
    """Direct Egypt business/markets news with article-level date verification."""
    URLS = [
        "https://english.ahram.org.eg/Category/3/14/Business/Markets--Companies.aspx",
    ]
    def __init__(self, name="egypt_news"): self.name=name

    @staticmethod
    def _article_date(html: str):
        import bs4
        soup=bs4.BeautifulSoup(html,"html.parser")
        for selector, attr in [
            ("meta[property='article:published_time']", "content"),
            ("meta[name='date']", "content"),
            ("meta[name='publishdate']", "content"),
        ]:
            node=soup.select_one(selector)
            if node and node.get(attr):
                try: return parse_date(node.get(attr)).isoformat()
                except Exception: pass
        text=" ".join(soup.stripped_strings)
        patterns=[
            r"Ahram Online\s*,?\s*\w+\s+(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+20\d{2})",
            r"Published\s+(\w+\s+\d{1,2},\s+20\d{2})",
            r"(\d{1,2}/\d{1,2}/20\d{2})",
        ]
        for pat in patterns:
            m=_re.search(pat,text,_re.I)
            if m:
                raw=m.group(1)
                for fmt in ("%d %b %Y","%B %d, %Y","%m/%d/%Y"):
                    try: return dtmod.datetime.strptime(raw,fmt).replace(tzinfo=dtmod.timezone.utc).isoformat()
                    except ValueError: pass
        return None

    async def fetch(self, tickers=None):
        import bs4
        headers={"User-Agent":"Money that matters/1.0"}
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=headers) as client:
                candidates=[]
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
                        link=httpx.URL(url).join(href)
                        link_s = str(link)
                        if not host_allowed(link_s, {"ahram.org.eg"}): continue
                        path = urlparse(link_s).path.lower()
                        # Stay inside Ahram Business > Markets & Companies.
                        # This prevents the page's Latest News / Most Viewed blocks
                        # from leaking politics or sports into the market feed.
                        if "/category/3/14/business/" not in path and "/allcategory/3/14/business/" not in path and "newscategoryid=14" not in link_s.lower(): continue
                        if not egypt_subject_ok(title, native=False): continue
                        banned = ["premier league", "football", "soccer", "ahly", "al ahly", "champions league", "tennis", "arsenal", "palestinians", "settlements", "ceasefire"]
                        if any(x in title.lower() for x in banned): continue
                        seen.add(href)
                        candidates.append((str(link),title))
                        if len(candidates)>=25: break
                    if len(candidates)>=25: break

                sem=asyncio.Semaphore(5)
                async def verify(link,title):
                    async with sem:
                        try:
                            rr=await client.get(link)
                            rr.raise_for_status()
                            published=self._article_date(rr.text)
                            if not published: return None
                            return {"id":hashlib.sha256(link.encode()).hexdigest()[:20],"ticker":None,"company":None,"headline":title,"outlet":(urlparse(link).hostname or "").removeprefix("www."),"published_at":published,"source_url":link,"lean":classify(title)}
                        except Exception:
                            return None
                verified=await asyncio.gather(*(verify(l,t) for l,t in candidates))
                items=[x for x in verified if x]
                if not items: return FeedResult([], "Egypt direct sources returned no verified records")
                return FeedResult(list({x["id"]:x for x in items}.values()))
        except Exception as exc:
            return FeedResult([], f"Egypt direct: {exc}")
