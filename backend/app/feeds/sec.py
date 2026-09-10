import asyncio, hashlib, re, xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import httpx
from .base import Feed, FeedResult
from .limiter import sec_limiter
from ..config import settings

SEC_UNIVERSE="https://www.sec.gov/files/company_tickers.json"

STATIC_CIKS = {
"AAPL":"320193","MSFT":"789019","NVDA":"1045810","AMZN":"1018724","META":"1326801","GOOGL":"1652044","GOOG":"1652044","AVGO":"1730168","TSLA":"1318605","BRK.B":"1067983","JPM":"19617","V":"1403161","MA":"1141391","LLY":"59478","WMT":"104169","XOM":"2115436","UNH":"731766","ORCL":"1341439","COST":"909832","HD":"354950","PG":"80424","JNJ":"200406","ABBV":"1551152","CRM":"1108524","AMD":"2488","NFLX":"1065280","ADBE":"796343","QCOM":"804328","INTC":"50863","CSCO":"858877"}


def text(node, path):
    x=node.find(path) if node is not None else None
    return (x.text or '').strip() if x is not None else None

def parse_form4(content):
    """Parse SEC Form 4 XML, tolerating malformed publisher XML without inventing data."""
    try:
        return ET.fromstring(content), "etree"
    except ET.ParseError:
        # Some public Form 4 documents have malformed XML. BeautifulSoup's
        # tolerant HTML parser lets us recover the fields that are actually
        # present while still requiring explicit Form 4 transaction tags.
        soup = BeautifulSoup(content, "html.parser")
        if not soup.find("nonderivativetransaction"):
            raise
        return soup, "soup"

def node_text(node, *names):
    for name in names:
        found = node.find(name) if hasattr(node, "find") else None
        if found is not None:
            value = getattr(found, "text", None)
            if value:
                return value.strip()
    return None

async def sec_get(client, url, headers, attempts=4):
    last=None
    for attempt in range(attempts):
        await sec_limiter.wait("sec")
        try:
            r=await client.get(url,headers=headers,timeout=30)
            if r.status_code not in (429,503): r.raise_for_status(); return r
            last=r
        except httpx.HTTPError:
            if attempt==attempts-1: raise
        retry=last.headers.get("Retry-After") if last else None
        try: delay=float(retry) if retry else min(90,10*(2**attempt))
        except ValueError: delay=min(90,10*(2**attempt))
        await asyncio.sleep(delay)
    last.raise_for_status()

class SecInsidersFeed(Feed):
    name="insiders"
    def __init__(self, client, db=None): self.client,self.db=client,db

    async def _universe(self, headers):
        if self.db is not None:
            cached=await self.db.sec_cache.find_one({"_id":"company_tickers"})
            if cached and cached.get("data") and cached.get("expires_at") and cached["expires_at"] > datetime.now(timezone.utc):
                return cached["data"]
        try:
            r=await sec_get(self.client,SEC_UNIVERSE,headers)
            raw={str(v['ticker']).upper():{"cik":str(v['cik_str']).zfill(10),"title":v.get('title')} for v in r.json().values()}
            data={}
            for k,v in raw.items():
                data[k]=v
                if k == "BRK-B": data["BRK.B"]=v
        except Exception:
            data={t:{"cik":c,"title":t} for t,c in STATIC_CIKS.items()}
        if self.db is not None:
            await self.db.sec_cache.update_one({"_id":"company_tickers"},{"$set":{"data":data,"expires_at":datetime.now(timezone.utc).replace(microsecond=0)+__import__('datetime').timedelta(hours=24)}},upsert=True)
        return data

    async def fetch(self, tickers=None):
        headers={"User-Agent":settings.sec_user_agent,"Accept-Encoding":"gzip, deflate"}
        try:
            universe=await self._universe(headers)
            wanted=[t.upper() for t in (tickers or {}) if re.fullmatch(r"[A-Z]{1,6}(?:\.[A-Z])?",t)]
            items=[]
            for ticker in wanted:
                meta=universe.get(ticker)
                if not meta: continue
                try:
                    sr=await sec_get(self.client,f"https://data.sec.gov/submissions/CIK{meta['cik']}.json",headers)
                except Exception:
                    continue
                recent=sr.json().get('filings',{}).get('recent',{})
                count=0
                for i,form in enumerate(recent.get('form',[])):
                    if form!='4' or count>=1: continue
                    accession=recent.get('accessionNumber',[''])[i]; filed=recent.get('filingDate',[''])[i]; primary=recent.get('primaryDocument',[''])[i]
                    if not accession or not primary: continue
                    archive=f"https://www.sec.gov/Archives/edgar/data/{int(meta['cik'])}/{accession.replace('-', '')}/{primary}"
                    try:
                        fr=await sec_get(self.client,archive,headers)
                        root, parser = parse_form4(fr.content)
                    except Exception:
                        # A malformed individual filing must never poison the
                        # entire insider feed. Skip only this filing.
                        continue
                    if parser == "etree":
                        issuer=(text(root,'.//issuerTradingSymbol') or ticker).upper()
                        owner=root.find('.//reportingOwner')
                        owner_name=text(owner,'.//rptOwnerName') if owner is not None else None
                        role=(text(owner,'.//officerTitle') if owner is not None else None) or ('Director' if text(owner,'.//isDirector')=='1' else None)
                        transactions=root.findall('.//nonDerivativeTransaction')
                    else:
                        issuer=(node_text(root, 'issuertradingsymbol') or ticker).upper()
                        owner=root.find('reportingowner')
                        owner_name=node_text(owner, 'rptownername') if owner is not None else None
                        role=(node_text(owner, 'officertitle') if owner is not None else None) or ('Director' if node_text(owner, 'isdirector')=='1' else None)
                        transactions=root.find_all('nonderivativetransaction')
                    if not re.fullmatch(r"[A-Z]{1,6}(?:\.[A-Z])?",issuer): continue
                    for tx in transactions:
                        if parser == "etree":
                            code=text(tx,'.//transactionCoding/transactionCode')
                            shares_text=text(tx,'.//transactionAmounts/transactionShares/value')
                            price_text=text(tx,'.//transactionAmounts/transactionPricePerShare/value')
                        else:
                            code=node_text(tx, 'transactioncode')
                            shares_text=node_text(tx, 'value') if False else node_text(tx.find('transactionamounts') if tx.find('transactionamounts') else tx, 'transactions' )
                            shares_node=tx.find('transactionshares')
                            price_node=tx.find('transactionpricepershare')
                            shares_text=node_text(shares_node, 'value') if shares_node is not None else None
                            price_text=node_text(price_node, 'value') if price_node is not None else None
                        if code not in ('P','S'): continue
                        try: shares=float(shares_text)
                        except (TypeError,ValueError): shares=None
                        try: price=float(price_text)
                        except (TypeError,ValueError): price=None
                        items.append({"id":hashlib.sha256((issuer+accession+str(len(items))).encode()).hexdigest()[:20],"ticker":issuer,"company":meta.get('title'),"insider_name":owner_name or 'Unavailable in filing',"role":role,"action":'buy' if code=='P' else 'sell',"shares":shares,"dollar_value":shares*price if shares is not None and price is not None else None,"filing_date":filed,"source_url":archive,"feed_mode":"live"})
                    count+=1
            return FeedResult(items)
        except Exception as exc: return FeedResult([],f"SEC: {exc}")
