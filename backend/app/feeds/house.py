import asyncio
import io
import logging
import zipfile
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
import httpx
from .base import Feed, FeedResult
from .limiter import HostLimiter

logger = logging.getLogger(__name__)
house_limiter = HostLimiter(0.25)
HOUSE_HOST = "disclosures-clerk.house.gov"

async def house_get(client, url, attempts=4):
    last = None
    for attempt in range(attempts):
        await house_limiter.wait(HOUSE_HOST)
        try:
            r = await client.get(url, timeout=30, follow_redirects=True)
            if r.status_code not in (429, 503):
                r.raise_for_status()
                return r
            retry = r.headers.get("Retry-After")
            delay = None
            if retry:
                try: delay = max(0.0, float(retry))
                except ValueError:
                    try: delay = max(0.0, (parsedate_to_datetime(retry) - datetime.now(parsedate_to_datetime(retry).tzinfo)).total_seconds())
                    except Exception: pass
            if delay is None: delay = min(8.0, 0.75 * (2 ** attempt))
            last = httpx.HTTPStatusError(f"House returned {r.status_code}", request=r.request, response=r)
            if attempt < attempts - 1: await asyncio.sleep(delay)
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
            last = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status not in (429, 503): raise
            if attempt < attempts - 1: await asyncio.sleep(min(8.0, 0.75 * (2 ** attempt)))
    raise last or RuntimeError("House request failed")

class HouseCongressFeed(Feed):
    name = "congress"
    def __init__(self, client): self.client = client
    async def fetch(self, year: int = 2026) -> FeedResult:
        url = f"https://{HOUSE_HOST}/public_disc/financial-pdfs/{year}FD.zip"
        try:
            r = await house_get(self.client, url)
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                names = [n for n in z.namelist() if n.lower().endswith('.xml')]
                if not names: return FeedResult(error="House archive contained no XML index")
                root = ET.fromstring(z.read(names[0]))
            items=[]
            for row in root.iter():
                data={c.tag.lower().split('}')[-1]:(c.text or '').strip() for c in row}
                if not data: continue
                member=data.get('member') or data.get('filingmember')
                doc=data.get('documentid') or data.get('docid')
                if not member or not doc: continue
                items.append({"id":doc,"member":member,"district":data.get('district'),"filing_date":data.get('filingdate',''),"document_id":doc,"source_url":"https://disclosures-clerk.house.gov/FinancialDisclosure","ticker":None,"action":None,"feed_mode":"live"})
            return FeedResult(items)
        except Exception as exc:
            logger.warning("House disclosure sync failed: %s", exc)
            return FeedResult(error=str(exc))
