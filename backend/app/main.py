import asyncio
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
from urllib.parse import urlparse
import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from .config import settings
from .feeds.news import GdeltNewsFeed, MarketDirectFeed, EgyptDirectFeed
from .feeds.sec import SecInsidersFeed, STATIC_CIKS
from .feeds.house import HouseCongressFeed
from .feeds.limiter import house_limiter, sec_limiter
from .services.scoring import Signal, money_match, direction
from .services.dates import utc_age
from .models import MoneyMatch

client = AsyncIOMotorClient(settings.mongodb_url)
db = client[settings.mongodb_db]

BUILD_VERSION = "v6-rate-limit-direct-first"
BASELINE = [x.strip().upper() for x in settings.baseline_tickers.split(',') if x.strip()]
sync_lock = asyncio.Lock()

async def save_feed(name, result):
    now = datetime.now(timezone.utc)
    if result.items:
        collection = {"market_news":"news", "egypt_news":"news", "insiders":"insiders", "congress":"congress"}[name]
        if collection == "news":
            await db[collection].delete_many({"feed": name})
            for item in result.items: item["feed"] = name
        else:
            await db[collection].delete_many({"feed": name})
            for item in result.items: item["feed"] = name
        if result.items:
            await db[collection].insert_many(result.items, ordered=False)
        await db.feed_state.update_one({"_id":name},{"$set":{"updated_at":now,"error":None,"count":len(result.items)}},upsert=True)
    elif result.error:
        await db.feed_state.update_one({"_id":name},{"$set":{"error":result.error,"last_attempt_at":now}},upsert=True)
    elif result.error is None:
        await db.feed_state.update_one({"_id":name},{"$set":{"updated_at":now,"error":None,"count":0}},upsert=True)
    elif not await db.feed_state.find_one({"_id":name}):
        await db.feed_state.insert_one({"_id":name,"updated_at":None,"error":result.error,"count":0})

async def ticker_map():
    # Do not make SEC company_tickers.json a prerequisite for refreshes.
    # Use the static CIK universe plus any cached SEC metadata.
    allmap={t:t for t in STATIC_CIKS}
    try:
        cached=await db.sec_cache.find_one({"_id":"company_tickers"})
        for ticker,meta in ((cached or {}).get("data") or {}).items():
            allmap[str(ticker).upper()]=meta.get("title") if isinstance(meta,dict) else meta
    except Exception:
        pass
    tracked={t:allmap.get(t) for t in BASELINE}
    docs=await db.news.find({"feed":"market_news","ticker":{"$ne":None}}, {"ticker":1,"company":1}).limit(2000).to_list(2000)
    for d in docs:
        if d.get("ticker"): tracked[d["ticker"].upper()]=d.get("company") or allmap.get(d["ticker"].upper())
    return {t:c for t,c in tracked.items() if t}

async def sync_all():
    if sync_lock.locked():
        return await status()
    async with sync_lock:
        return await _sync_all_locked()

async def _sync_all_locked():
    tracked=await ticker_map()
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        market_feed = GdeltNewsFeed("market_news", settings.market_domains.split(','))
        insider_feed = SecInsidersFeed(c, db)
        congress_feed = HouseCongressFeed(c)
        egypt_feed = GdeltNewsFeed("egypt_news", settings.egypt_domains.split(','), egypt=True)
        egypt_direct = EgyptDirectFeed()
        market_direct = MarketDirectFeed()

        # Direct allow-listed publisher feeds are primary. GDELT is only a
        # discovery fallback and can never overwrite a successful direct feed.
        try:
            market_result = await market_direct.fetch(tracked)
        except Exception as exc:
            market_result = type("R", (), {"items":[], "error":f"Market direct: {exc}"})()
        if not market_result.items:
            try:
                market_result = await market_feed.fetch(tracked)
            except Exception as exc:
                market_result = type("R", (), {"items":[], "error":f"GDELT: {exc}"})()

        try:
            insider_result = await insider_feed.fetch(tickers=tracked)
        except Exception as exc:
            insider_result = type("R", (), {"items":[], "error":f"SEC: {exc}"})()

        try:
            congress_result = await congress_feed.fetch()
        except Exception as exc:
            congress_result = type("R", (), {"items":[], "error":f"House: {exc}"})()

        try:
            egypt_result = await egypt_direct.fetch()
        except Exception as exc:
            egypt_result = type("R", (), {"items":[], "error":f"Egypt direct: {exc}"})()
        if not egypt_result.items:
            try:
                egypt_result = await egypt_feed.fetch({})
            except Exception as exc:
                egypt_result = type("R", (), {"items":[], "error":f"GDELT: {exc}"})()

    for name, result in zip(("market_news", "insiders", "congress", "egypt_news"),
                            (market_result, insider_result, congress_result, egypt_result)):
        await save_feed(name, result)
    return await status()

async def scheduler():
    while True:
        try:
            await sync_all()
        except Exception as exc:
            print(f"sync_all failed: {exc!r}", flush=True)
        await asyncio.sleep(max(1,settings.refresh_hours)*3600)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task=asyncio.create_task(scheduler())
    yield
    task.cancel(); client.close()

app=FastAPI(title="Money that matters API",version="1.1.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=[settings.frontend_origin],allow_credentials=False,allow_methods=["GET","POST"],allow_headers=["*"])

async def feed_status(name):
    doc=await db.feed_state.find_one({"_id":name})
    if not doc or not doc.get("updated_at"): return {"name":name,"mode":"empty","updated_at":None,"error":doc.get("error") if doc else None}
    updated_at=doc["updated_at"]
    age=utc_age(updated_at)
    return {"name":name,"mode":"live" if age<=timedelta(hours=24) else "stale","updated_at":updated_at.isoformat(),"error":doc.get("error"),"count":doc.get("count",0)}

async def status(): return {"build":BUILD_VERSION,"feeds":[await feed_status(n) for n in ("market_news","insiders","congress","egypt_news")]}

@app.get("/api/health")
async def health():
    try: await db.command("ping")
    except Exception as e: raise HTTPException(503,str(e))
    return {"ok":True,"service":"money-that-matters","build":BUILD_VERSION}

@app.get("/api/status")
async def api_status(response: Response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return await status()

async def list_feed(collection, feed, sortfield, limit):
    docs=await db[collection].find({"feed":feed}).sort(sortfield,-1).limit(limit).to_list(limit)
    return [{k:v for k,v in d.items() if k not in {"_id","feed"}} for d in docs]

@app.get("/api/news")
async def news(limit:int=50): return {"items":await list_feed("news","market_news","published_at",limit),"status":await feed_status("market_news")}

@app.get("/api/egypt")
async def egypt(limit:int=50): return {"items":await list_feed("news","egypt_news","published_at",limit),"status":await feed_status("egypt_news")}

@app.get("/api/insiders")
async def insiders(limit:int=100): return {"items":await list_feed("insiders","insiders","filing_date",limit),"status":await feed_status("insiders")}

@app.get("/api/congress")
async def congress(limit:int=100): return {"items":await list_feed("congress","congress","filing_date",limit),"status":await feed_status("congress")}

@app.get("/api/matches")
async def matches(limit:int=100):
    feed_modes={n:(await feed_status(n))["mode"] for n in ("market_news","insiders","congress")}
    docs=[]
    docs += await db.news.find({"feed":"market_news","ticker":{"$ne":None}}).sort("published_at",-1).limit(1000).to_list(1000)
    docs += await db.insiders.find({"feed":"insiders","ticker":{"$ne":None}}).sort("filing_date",-1).limit(1000).to_list(1000)
    grouped={}
    for d in docs: grouped.setdefault(d["ticker"].upper(),[]).append(d)
    out=[]
    for ticker,items in grouped.items():
        company=next((i.get("company") for i in items if i.get("company")),None)
        signals=[]; fired=[]; stale=[]
        seen=set()
        for i in items:
            source="news" if i.get("feed")=="market_news" else "insiders"
            if source in seen: continue
            seen.add(source)
            mode=feed_modes["market_news" if source=="news" else "insiders"]
            lean=i.get("lean","neutral") if source=="news" else ("bullish" if i.get("action")=="buy" else "bearish" if i.get("action")=="sell" else "neutral")
            signals.append(Signal(source,lean,1.0,mode=="stale",True))
            (stale if mode=="stale" else fired).append(source)
        score=money_match(signals)
        out.append(MoneyMatch(ticker=ticker,company=company,score=score,direction=direction(signals),fired_sources=fired,stale_sources=stale,strong_match=score>=60 and len(set(fired))==3).model_dump())
    out.sort(key=lambda x:(x["score"],len(x["fired_sources"])),reverse=True)
    return {"items":out[:limit]}

@app.get("/api/ticker/{ticker}")
async def ticker_detail(ticker: str):
    ticker=ticker.upper()
    news_docs=await db.news.find({"feed":"market_news","ticker":ticker}).sort("published_at",-1).limit(20).to_list(20)
    insider_docs=await db.insiders.find({"feed":"insiders","ticker":ticker}).sort("filing_date",-1).limit(20).to_list(20)
    congress_docs=[]  # House public index is filing-level and has no verified ticker field.
    def clean(d): return {k:v for k,v in d.items() if k not in {"_id","feed"}}
    return {"ticker":ticker,"news":[clean(x) for x in news_docs],"insiders":[clean(x) for x in insider_docs],"congress":congress_docs,"note":"Congress is filing-level in the free public path and therefore cannot be attributed to this ticker without a licensed transaction-level dataset."}

@app.post("/api/refresh")
async def refresh():
    return {"accepted":True,"status":await sync_all()}

@app.get("/api/refresh")
async def refresh_get(response: Response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return await refresh()
