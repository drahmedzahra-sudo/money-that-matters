import asyncio
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from .config import settings
from .feeds.news import EgyptDirectFeed, EgyptEGXFeed
from .services.dates import utc_age

client = AsyncIOMotorClient(settings.mongodb_url)
db = client[settings.mongodb_db]
BUILD_VERSION = "v15-egypt-only-runtime"
sync_lock = asyncio.Lock()

async def feed_status():
    doc = await db.feed_state.find_one({"_id": "egypt_news"})
    if not doc or not doc.get("updated_at"):
        return {"name":"egypt_news","mode":"empty","updated_at":None,"error":doc.get("error") if doc else None,"count":doc.get("count",0) if doc else 0}
    updated_at = doc["updated_at"]
    age = utc_age(updated_at)
    return {"name":"egypt_news","mode":"live" if age <= timedelta(hours=24) else "stale","updated_at":updated_at.isoformat(),"error":doc.get("error"),"count":doc.get("count",0)}

async def save_egypt(result):
    now = datetime.now(timezone.utc)
    if result.items:
        await db.news.delete_many({"feed":"egypt_news"})
        for item in result.items:
            item["feed"] = "egypt_news"
        await db.news.insert_many(result.items, ordered=False)
        await db.feed_state.update_one({"_id":"egypt_news"},{"$set":{"updated_at":now,"error":None,"count":len(result.items),"last_attempt_at":now}},upsert=True)
    else:
        # Never overwrite verified cached data with an empty/failed fetch.
        await db.feed_state.update_one({"_id":"egypt_news"},{"$set":{"error":result.error or "No verified Egypt market records","last_attempt_at":now}},upsert=True)

async def sync_egypt():
    if sync_lock.locked():
        st = await feed_status()
        st["running"] = True
        return {"build":BUILD_VERSION,"feeds":[st],"running":True}
    async with sync_lock:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent":"Money that matters/1.0"}) as client_http:
            egx_feed = EgyptEGXFeed()
            ahram_feed = EgyptDirectFeed()
            egx, ahram = await asyncio.gather(
                egx_feed.fetch(),
                ahram_feed.fetch(),
            )
        merged = {}
        for result in (egx, ahram):
            for item in result.items:
                merged[item["id"]] = item
        if merged:
            from .feeds.base import FeedResult
            errors = [x.error for x in (egx, ahram) if x.error]
            result = FeedResult(list(merged.values()), "; ".join(errors) if errors else None)
        else:
            from .feeds.base import FeedResult
            errors = [x.error for x in (egx, ahram) if x.error]
            result = FeedResult([], "; ".join(errors) if errors else "No verified Egypt market records")
        await save_egypt(result)
        st = await feed_status()
        return {"build":BUILD_VERSION,"feeds":[st],"running":False}

async def scheduler():
    while True:
        try:
            await sync_egypt()
        except Exception as exc:
            print(f"sync_egypt failed: {exc!r}", flush=True)
        await asyncio.sleep(max(1, settings.refresh_hours) * 3600)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(scheduler())
    yield
    task.cancel()
    client.close()

app = FastAPI(title="Money that matters EGX API", version="1.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_origin], allow_credentials=False, allow_methods=["GET","POST"], allow_headers=["*"])

@app.get("/api/health")
async def health():
    try: await db.command("ping")
    except Exception as e: raise HTTPException(503, str(e))
    return {"ok":True,"service":"money-that-matters","build":BUILD_VERSION}

@app.get("/api/status")
async def status(response: Response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    st = await feed_status()
    return {"build":BUILD_VERSION,"feeds":[st],"running":sync_lock.locked()}

@app.get("/api/build-manifest")
async def build_manifest():
    return {"build":BUILD_VERSION,"market":"Egypt / EGX only","sources":["Egyptian Exchange (EGX)","Ahram Online Markets & Companies"],"policy":"No synthetic data; failed fetches never replace verified cache."}

async def list_egypt(limit:int=50):
    docs = await db.news.find({"feed":"egypt_news"}).sort("published_at", -1).limit(limit).to_list(limit)
    return [{k:v for k,v in d.items() if k not in {"_id","feed"}} for d in docs]

@app.get("/api/egypt")
async def egypt(limit:int=50):
    return {"items":await list_egypt(limit),"status":await feed_status()}

@app.post("/api/refresh")
async def refresh():
    return {"accepted":True,"status":await sync_egypt()}

@app.get("/api/refresh")
async def refresh_get(response: Response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return await refresh()
