import asyncio, hashlib, re, xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import httpx
from .base import Feed, FeedResult
from .limiter import sec_limiter
from ..config import settings

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

async def sec_get(client, url, headers, attempts=1):
    last=None
    for attempt in range(attempts):
        await sec_limiter.wait("sec")
        try:
            r=await client.get(url,headers=headers,timeout=20)
            if r.status_code not in (429,503):
                r.raise_for_status(); return r
            last=r
        except httpx.HTTPError:
            if attempt==attempts-1: raise
        retry=last.headers.get("Retry-After") if last else None
        try: delay=min(20.0, max(2.0, float(retry))) if retry else 5.0
        except ValueError: delay=5.0
        await asyncio.sleep(delay)
    if last is not None:
        last.raise_for_status()
    raise RuntimeError("SEC request failed")

class SecInsidersFeed(Feed):
    name="insiders"
    def __init__(self, client, db=None): self.client,self.db=client,db

    async def _universe(self, headers):
        # Do not depend on SEC company_tickers.json during every refresh.
        # That endpoint is optional metadata and can be rate-limited; the
        # baseline CIK map is authoritative enough for the tracked universe.
        data={t:{"cik":c,"title":t} for t,c in STATIC_CIKS.items()}
        if self.db is not None:
            try:
                cached=await self.db.sec_cache.find_one({"_id":"company_tickers"})
                cached_data=(cached or {}).get("data") or {}
                if cached_data:
                    data.update(cached_data)
            except Exception:
                pass
        return data

    async def fetch(self, tickers=None):
        headers={"User-Agent":settings.sec_user_agent,"Accept-Encoding":"gzip, deflate"}
        try:
            universe=await self._universe(headers)
            wanted=[t.upper() for t in (tickers or {}) if re.fullmatch(r"[A-Z]{1,6}(?:\.[A-Z])?",t)]
            # SEC requests are I/O bound. Run a small bounded number in parallel;
            # the shared host limiter still enforces the SEC request interval.
            semaphore=asyncio.Semaphore(6)

            async def one_ticker(ticker):
                meta=universe.get(ticker)
                if not meta:
                    return [], None
                async with semaphore:
                    try:
                        sr=await sec_get(self.client,f"https://data.sec.gov/submissions/CIK{meta['cik']}.json",headers)
                    except Exception as exc:
                        return [], f"{ticker}: {exc}"
                    try:
                        payload=sr.json()
                        recent=payload.get('filings',{}).get('recent',{})
                    except Exception as exc:
                        return [], f"{ticker}: invalid SEC JSON: {exc}"
                    company=payload.get('name') or meta.get('title') or ticker
                    for i,form in enumerate(recent.get('form',[])):
                        if form!='4':
                            continue
                        accession=recent.get('accessionNumber',[''])[i]
                        filed=recent.get('filingDate',[''])[i]
                        primary=recent.get('primaryDocument',[''])[i]
                        if not accession or not primary:
                            continue
                        archive=f"https://www.sec.gov/Archives/edgar/data/{int(meta['cik'])}/{accession.replace('-', '')}/{primary}"
                        try:
                            fr=await sec_get(self.client,archive,headers)
                            root, parser = parse_form4(fr.content)
                        except Exception as exc:
                            return [], f"{ticker} filing: {exc}"
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
                        if not re.fullmatch(r"[A-Z]{1,6}(?:\.[A-Z])?",issuer):
                            return [], None
                        items=[]
                        for tx in transactions:
                            if parser == "etree":
                                code=text(tx,'.//transactionCoding/transactionCode')
                                shares_text=text(tx,'.//transactionAmounts/transactionShares/value')
                                price_text=text(tx,'.//transactionAmounts/transactionPricePerShare/value')
                            else:
                                code=node_text(tx, 'transactioncode')
                                shares_node=tx.find('transactionshares')
                                price_node=tx.find('transactionpricepershare')
                                shares_text=node_text(shares_node, 'value') if shares_node is not None else None
                                price_text=node_text(price_node, 'value') if price_node is not None else None
                            if code not in ('P','S'): continue
                            try: shares=float(shares_text)
                            except (TypeError,ValueError): shares=None
                            try: price=float(price_text)
                            except (TypeError,ValueError): price=None
                            items.append({"id":hashlib.sha256((issuer+accession+str(len(items))).encode()).hexdigest()[:20],"ticker":issuer,"company":company,"insider_name":owner_name or 'Unavailable in filing',"role":role,"action":'buy' if code=='P' else 'sell',"shares":shares,"dollar_value":shares*price if shares is not None and price is not None else None,"filing_date":filed,"source_url":archive,"feed_mode":"live"})
                        return items, None
                    return [], None

            results=await asyncio.gather(*(one_ticker(t) for t in wanted))
            items=[]
            failures=[]
            for ticker_items,error in results:
                items.extend(ticker_items)
                if error:
                    failures.append(error)
            if items:
                return FeedResult(items, "SEC partial failures: " + "; ".join(failures[:3]) if failures else None)
            if failures:
                return FeedResult([], "SEC upstream unavailable: " + "; ".join(failures[:3]))
            return FeedResult([])
        except Exception as exc:
            return FeedResult([],f"SEC: {exc}")
