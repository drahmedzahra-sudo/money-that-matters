import csv, io, zipfile, xml.etree.ElementTree as ET
from .base import Feed, FeedResult
from .limiter import house_limiter

HOUSE_SOURCE="https://disclosures-clerk.house.gov/FinancialDisclosure"

class HouseCongressFeed(Feed):
    name="congress"
    def __init__(self, client): self.client=client

    def _rows_from_text(self, raw):
        text=raw.decode("utf-8-sig", "replace")
        # House archives have historically used tab-delimited TXT indexes,
        # but tolerate commas/semicolons without inventing fields.
        sample=text[:4096]
        try:
            dialect=csv.Sniffer().sniff(sample, delimiters="\t,;")
            delimiter=dialect.delimiter
        except csv.Error:
            delimiter="\t"
        rows=list(csv.DictReader(io.StringIO(text), delimiter=delimiter))
        return rows

    def _rows_from_xml(self, raw):
        root=ET.fromstring(raw)
        rows=[]
        for row in root.iter():
            data={c.tag.lower().split("}")[-1]:(c.text or "").strip() for c in row}
            if data: rows.append(data)
        return rows

    async def fetch(self, year=2026):
        url=f"https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.zip"
        try:
            await house_limiter.wait("disclosures-clerk.house.gov")
            r=await self.client.get(url,timeout=30)
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                names=z.namelist()
                xml_name=next((n for n in names if n.lower()==f"{year}fd.xml".lower()), None)
                txt_name=next((n for n in names if n.lower()==f"{year}fd.txt".lower()), None)
                if not xml_name and not txt_name:
                    txt_name=next((n for n in names if n.lower().endswith(".txt")), None)
                if not xml_name and not txt_name:
                    return FeedResult(error="House archive contained no filing index")
                rows=None
                if xml_name:
                    try:
                        rows=self._rows_from_xml(z.read(xml_name))
                        if not rows:
                            rows=None
                    except Exception:
                        # The public XML index can be malformed. Fall back to
                        # the official TXT index from the same House archive.
                        rows=None
                if rows is None and txt_name:
                    rows=self._rows_from_text(z.read(txt_name))
            items=[]
            for data in rows or []:
                filing_type=(data.get("filingtype") or data.get("filing_type") or "").strip().upper()
                if filing_type and filing_type != "P":
                    continue
                doc=(data.get("docid") or data.get("documentid") or "").strip()
                if not doc: continue
                first=(data.get("first") or "").strip()
                last=(data.get("last") or "").strip()
                suffix=(data.get("suffix") or "").strip()
                member=" ".join(x for x in (first,last,suffix) if x) or (data.get("member") or data.get("filingmember") or "").strip()
                if not member: continue
                district=(data.get("statedst") or data.get("district") or "").strip() or None
                filing_date=(data.get("filingdate") or "").strip()
                items.append({"id":doc,"member":member,"district":district,"filing_date":filing_date,"document_id":doc,"filing_type":filing_type or "P","source_url":HOUSE_SOURCE,"ticker":None,"action":None,"feed_mode":"live"})
            return FeedResult(items)
        except Exception as exc:
            return FeedResult(error=f"House: {exc}")
