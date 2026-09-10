import hashlib, re, xml.etree.ElementTree as ET
import httpx
from .base import Feed, FeedResult
from ..config import settings

def text(node, path):
    x=node.find(path)
    return (x.text or '').strip() if x is not None else None

class SecInsidersFeed(Feed):
    name = "insiders"
    def __init__(self, client: httpx.AsyncClient): self.client = client

    async def fetch(self, tickers: dict[str, str] | None = None) -> FeedResult:
        headers={"User-Agent":settings.sec_user_agent,"Accept-Encoding":"gzip, deflate"}
        try:
            r=await self.client.get("https://www.sec.gov/files/company_tickers.json",headers=headers,timeout=30); r.raise_for_status()
            universe={str(v['ticker']).upper():{"cik":str(v['cik_str']).zfill(10),"title":v.get('title')} for v in r.json().values()}
            wanted=[t.upper() for t in (tickers or {}) if re.fullmatch(r"[A-Z]{1,6}(?:\.[A-Z])?",t)]
            items=[]
            for ticker in wanted:
                meta=universe.get(ticker)
                if not meta: continue
                sr=await self.client.get(f"https://data.sec.gov/submissions/CIK{meta['cik']}.json",headers=headers,timeout=30); sr.raise_for_status()
                recent=sr.json().get('filings',{}).get('recent',{})
                count=0
                for i,form in enumerate(recent.get('form',[])):
                    if form!='4' or count>=5: continue
                    accession=recent.get('accessionNumber',[''])[i]; filed=recent.get('filingDate',[''])[i]; primary=recent.get('primaryDocument',[''])[i]
                    if not accession or not primary: continue
                    archive=f"https://www.sec.gov/Archives/edgar/data/{int(meta['cik'])}/{accession.replace('-', '')}/{primary}"
                    try:
                        fr=await self.client.get(archive,headers=headers,timeout=30); fr.raise_for_status()
                        root=ET.fromstring(fr.content)
                    except Exception:
                        continue
                    issuer_symbol=(text(root,'.//issuerTradingSymbol') or ticker).upper()
                    if not re.fullmatch(r"[A-Z]{1,6}(?:\.[A-Z])?",issuer_symbol): continue
                    owner=root.find('.//reportingOwner')
                    owner_name=text(owner,'.//rptOwnerName') if owner is not None else None
                    role=(text(owner,'.//officerTitle') if owner is not None else None) or ('Director' if text(owner,'.//isDirector')=='1' else None)
                    for tx in root.findall('.//nonDerivativeTransaction'):
                        code=text(tx,'.//transactionCoding/transactionCode')
                        action='buy' if code=='P' else 'sell' if code=='S' else 'unknown'
                        shares_raw=text(tx,'.//transactionAmounts/transactionShares/value')
                        price_raw=text(tx,'.//transactionAmounts/transactionPricePerShare/value')
                        try: shares=float(shares_raw) if shares_raw else None
                        except ValueError: shares=None
                        try: price=float(price_raw) if price_raw else None
                        except ValueError: price=None
                        value=shares*price if shares is not None and price is not None else None
                        items.append({"id":hashlib.sha256((ticker+accession+str(len(items))).encode()).hexdigest()[:20],"ticker":issuer_symbol,"company":meta.get('title'),"insider_name":owner_name or 'Unavailable in filing',"role":role,"action":action,"shares":shares,"dollar_value":value,"filing_date":filed,"source_url":archive,"feed_mode":"live"})
                    count+=1
            return FeedResult(items)
        except Exception as exc: return FeedResult([],str(exc))
