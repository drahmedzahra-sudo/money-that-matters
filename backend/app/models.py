from typing import Literal, Optional
from pydantic import BaseModel, Field

FeedMode = Literal["live", "stale", "empty"]
Lean = Literal["bullish", "neutral", "bearish"]

class FeedStatus(BaseModel):
    name: str
    mode: FeedMode
    updated_at: Optional[str] = None
    error: Optional[str] = None

class NewsItem(BaseModel):
    id: str
    ticker: Optional[str] = None
    company: Optional[str] = None
    headline: str
    outlet: str
    published_at: str
    source_url: str
    lean: Lean
    feed_mode: FeedMode = "live"

class InsiderTrade(BaseModel):
    id: str
    ticker: str
    company: Optional[str] = None
    insider_name: str
    role: Optional[str] = None
    action: Literal["buy", "sell", "unknown"]
    shares: Optional[float] = None
    dollar_value: Optional[float] = None
    filing_date: str
    source_url: str
    feed_mode: FeedMode = "live"

class CongressFiling(BaseModel):
    id: str
    member: str
    district: Optional[str] = None
    filing_date: str
    document_id: str
    source_url: str
    ticker: Optional[str] = None
    action: Optional[str] = None
    feed_mode: FeedMode = "live"

class MoneyMatch(BaseModel):
    ticker: str
    company: Optional[str] = None
    score: int = Field(ge=0, le=100)
    direction: Lean
    fired_sources: list[str]
    stale_sources: list[str]
    strong_match: bool
