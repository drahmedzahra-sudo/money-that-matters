# Deployment checklist

1. MongoDB: managed MongoDB service or private MongoDB cluster.
2. API: deploy FastAPI with Uvicorn/Gunicorn equivalent, HTTPS only.
3. Frontend: build with Vite and serve static assets from a CDN/static host.
4. CORS: set `FRONTEND_ORIGIN` to the exact production frontend URL.
5. SEC: set a descriptive real contact in `SEC_USER_AGENT`, for example `Money that matters admin@your-real-domain.example`. SEC says scripted clients should identify themselves and stay at or below 10 requests/second.
6. Scheduler: run the refresh worker hourly or another conservative cadence, with exponential backoff and one shared host limiter. Do not create module-level asyncio locks.
7. Congress: House filing-level feed is not equivalent to transaction-level trade data. Before monetization, resolve the Senate disclosure commercial-use restrictions with counsel and choose a licensed ticker-level provider if three-source scoring is required.
8. Egypt: verify publisher terms and current RSS/scraping availability before enabling automated pulls for any publisher without an official feed.
9. Observability: retain feed state, error class, last successful sync, and item counts. Never overwrite cached data on a failed sync.
10. Deployment is intentionally not performed by this project.
