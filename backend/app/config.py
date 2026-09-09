from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    mongodb_url: str = "mongodb://localhost:27017"
    mongodb_db: str = "money_that_matters"
    sec_user_agent: str = "Money that matters contact@example.com"
    frontend_origin: str = "http://localhost:5173"
    refresh_hours: int = 1
    gdelt_min_seconds: float = 5.0
    baseline_tickers: str = "AAPL,MSFT,NVDA,AMZN,META,GOOGL,GOOG,AVGO,TSLA,BRK.B,JPM,V,MA,LLY,WMT,XOM,UNH,ORCL,COST,HD,PG,JNJ,ABBV,CRM,AMD,NFLX,ADBE,QCOM,INTC,CSCO"
    market_domains: str = "reuters.com,cnbc.com,bloomberg.com,wsj.com"
    egypt_domains: str = "reuters.com,bloomberg.com,cnbc.com,wsj.com,zawya.com,apnews.com,enterprise.news,mubasher.info,almalnews.com,alborsaanews.com,masrawy.com,shorouknews.com,ahram.org.eg,egx.com.eg,cbe.org.eg,capmas.gov.eg"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
