import csv, io, zipfile, xml.etree.ElementTree as ET
from .base import Feed, FeedResult
from .limiter import house_limiter

HOUSE_SOURCE="https://disclosures-clerk.house.gov/FinancialDisclosure"

class HouseCongressFeed(Feed):
    name="congress"
    def __init__(self, client): self.client=client

    @staticmethod
    def _rows_from_text(raw):
        text=raw.decode("utf-8-sig", "replace")
        sample=text[:8192]
        for delimiter in ("\t", ",", ";"):
            try:
                rows=list(csv.DictReader(io.StringIO(text), delimiter=delimiter))
                if rows and any((r.get("DocID") or r.get("docid") or r.get("DocumentID") or r.get("documentid")) for r in rows):
                    return rows
            except csv.Error:
                pass
        return []

    @staticmethod
    def _rows_from_xml(raw):
        root=ET.fromstring(raw)
        rows=[]
        for row in root.iter():
            data={c.tag.lower().split("}")[-1]:(c.text or "").strip() for c in row}
            if data and (data.get("docid") or data.get("documentid")):
                rows.append(data)
        return rows

    async def fetch(self, year=2026):
        url=f"https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
        try:
            await house_limiter.wait("disclosures-clerk.house.gov")
            r=await self.client.get(url,timeout=30)
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                names=z.namelist()
                txt_name=next((n for n in names if n.lower()==f"{year}fd.txt"),None)
                if not txt_name:
                    txt_name=next((n for n in names if n.lower().endswith(".txt")),None)
                xml_name=next((n for n in names if n.lower()==f"{year}fd.xml"),None)
                rows=[]
                if txt_name:
                    rows=self._rows_from_text(z.read(txt_name))
                if not rows and xml_name:
                    try:
                        rows=self._rows_from_xml(z.read(xml_name))
                    except ET.ParseError:
                        rows=[]
            if not rows:
                return FeedResult([], "House filing index contained no parseable rows")

            items=[]
            for data in rows:
                normalized={str(k).lower().replace("_", ""): (v or "").strip() for k,v in data.items()}
                filing_type=(normalized.get("filingtype") or "").upper()
                if filing_type and filing_type != "P":
                    continue
                doc=normalized.get("docid") or normalized.get("documentid")
                if not doc:
                    continue
                first=normalized.get("first") or ""
                last=normalized.get("last") or ""
                suffix=normalized.get("suffix") or ""
                member=" ".join(x for x in (first,last,suffix) if x).strip()
                if not member:
                    member=normalized.get("member") or normalized.get("filingmember") or ""
                if not member:
                    continue
                district=normalized.get("statedst") or normalized.get("district") or None
                filing_date=normalized.get("filingdate") or ""
                items.append({
                    "id":doc,
                    "member":member,
                    "district":district,
                    "filing_date":filing_date,
                    "document_id":doc,
                    "filing_type":filing_type or "P",
                    "source_url":HOUSE_SOURCE,
                    "ticker":None,
                    "action":None,
                    "feed_mode":"live",
                })
            return FeedResult(items)
        except Exception as exc:
            return FeedResult([], f"House: {exc}")
