# Money that matters

A production-oriented, mobile-first dashboard for public-market signals. No login, no demo data, no deployment included.

## What is actually implemented

- React + Vite + Tailwind CSS frontend.
- FastAPI + Motor/MongoDB backend.
- Six tabs: Money Match, Market News, Insiders, Congress, Egypt, Watchlist.
- Local watchlist persistence.
- Money Match scoring with explicit coverage multiplier and stale-feed exclusion.
- Ticker detail view showing the underlying verified news and Form 4 records.
- SEC company ticker resolution and Form 4 XML transaction parsing for baseline/dynamically discovered tickers.
- House Clerk filing-index ingestion at filing level only.
- GDELT-backed market and Egypt discovery, followed by publisher host and subject gates. GDELT is used only as an index, and the displayed publisher is the article's actual URL host.
- Live/stale/empty feed state persisted in MongoDB. Failed refreshes never delete last-known-good data.
- Automated hourly refresh worker inside FastAPI, plus manual Refresh.
- Automated tests for scoring, stale behavior, date parsing, source boundaries, relevance gates, and forbidden sample/demo modules.

## Honest limitations

### Congress
The free House path is filing-level. The House Clerk's own site warns that use of the information for commercial purposes is restricted except for news and communications media dissemination. This project therefore does not claim ticker-level congressional trades from those filings, and it does not scrape protected PDFs. A licensed transaction-level dataset is required for a true third Congress signal.

### News
GDELT is an index. It is not treated as the publisher. The application checks the final article URL against the allow-list and only then stores the item. Current publisher terms and feed availability must be reviewed before commercial use.

### SEC
The SEC adapter uses a declared User-Agent and the public EDGAR resources. It parses Form 4 XML when available, but an issuer's filing may still be unavailable or malformed. Missing transaction fields remain missing rather than being guessed.

## Local setup

### Option A, easiest MongoDB setup

Install Docker Desktop, then from the project root:

```bash
docker compose -f docker-compose.local.yml up -d
```

### Backend

```bash
cd backend
cp .env.example .env
```

Edit `.env` and replace:

```text
SEC_USER_AGENT=Money that matters your-real-email@example.com
```

Use a real contact address for automated SEC access.

Then:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. pytest -q
uvicorn app.main:app --reload --port 8000
```

Windows PowerShell activation:

```powershell
.venv\\Scripts\\Activate.ps1
```

### Frontend

Open a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL, normally `http://localhost:5173`.

If the API is not on localhost:8000, create `frontend/.env`:

```text
VITE_API_URL=https://your-api.example.com/api
```

Do not put MongoDB credentials or SEC credentials in the frontend environment.

## First run

1. Start MongoDB.
2. Start FastAPI.
3. Start Vite.
4. Open Money that matters.
5. The backend scheduler performs an initial sync when FastAPI starts.
6. You can also press Refresh in the header.
7. If a source is unavailable, the UI must show `stale` or `empty`, never invented records.

The first sync can take time because SEC requests are intentionally conservative and the news index is queried through GDELT. This is expected.

## Production preparation, do not deploy yet

- Put MongoDB behind authentication and private networking.
- Run FastAPI behind HTTPS.
- Set `FRONTEND_ORIGIN` to the exact production frontend origin, never `*`.
- Set a real SEC User-Agent contact address.
- Store secrets in the host's secret manager, not in git.
- Add process supervision for FastAPI.
- For horizontal scaling, move the scheduler into a single dedicated worker so multiple API replicas do not run duplicate refresh jobs.
- Review SEC, House Clerk, Senate Ethics, GDELT, and each publisher's current terms before monetization.
- Obtain legal advice before offering the Congress tab commercially.
- Add observability for source status, 429s, timeouts, parser failures, and cache age.
- Do not publish without owner approval.

## Verification

The backend test suite currently passes locally in this build.

The execution environment used to assemble this package could not complete `npm install` because outbound package resolution timed out, and it could not directly resolve the GDELT hostname. Therefore a browser-level production verification of the live feeds has not been claimed here.

## Sources

SEC EDGAR developer and fair-access guidance:
https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data

SEC developer resources:
https://www.sec.gov/about/developer-resources

House Clerk Financial Disclosure Reports:
https://disclosures-clerk.house.gov/FinancialDisclosure/ViewSearch

GDELT DOC 2.0 documentation and domain operators:
https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/


## Current scope
Egypt / EGX only. The runtime refreshes official EGX disclosures/news plus verified Ahram Online Markets & Companies articles. US SEC/Congress feeds are not active in this Egypt-only build.
