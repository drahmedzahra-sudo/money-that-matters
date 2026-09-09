import io, zipfile, xml.etree.ElementTree as ET
from .base import Feed, FeedResult

class HouseCongressFeed(Feed):
    name = "congress"
    def __init__(self, client): self.client = client
    async def fetch(self, year: int = 2026) -> FeedResult:
        url = f"https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
        try:
            r = await self.client.get(url, timeout=30); r.raise_for_status()
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
        except Exception as exc: return FeedResult(error=str(exc))
