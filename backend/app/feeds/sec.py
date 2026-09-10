import asyncio
import hashlib
import logging
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

import httpx

from .base import Feed, FeedResult
from .limiter import HostLimiter
from ..config import settings

logger = logging.getLogger(__name__)

# SEC publishes a 10 requests/second guideline. Keep a small safety margin and
# share the limiter across all SEC hosts used by this feed.
sec_limiter = HostLimiter(0.12)


def text(node, path):
    x = node.find(path)
    return (x.text or '').strip() if x is not None and x.text else None


def valid_symbol(value: str | None) -> bool:
    return bool(value and re.fullmatch(r"[A-Z]{1,6}(?:[.-][A-Z])?", value.upper()))


def symbol_aliases(value: str) -> set[str]:
    value = value.upper().strip()
    return {value, value.replace('.', '-'), value.replace('-', '.')}


async def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get('Retry-After')
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
            return max(0.0, dt.timestamp() - datetime.now(timezone.utc).timestamp())
        except Exception:
            return None


async def sec_get(client: httpx.AsyncClient, url: str, headers: dict, attempts: int = 4) -> httpx.Response:
    host = httpx.URL(url).host or 'www.sec.gov'
    last_exc = None
    for attempt in range(attempts):
        await sec_limiter.wait(host)
        try:
            response = await client.get(url, headers=headers, timeout=30)
            if response.status_code not in (429, 503):
                response.raise_for_status()
                return response
            retry_after = await _retry_after_seconds(response)
            delay = retry_after if retry_after is not None else min(8.0, 0.75 * (2 ** attempt))
            logger.warning('SEC %s from %s; retrying in %.2fs', response.status_code, host, delay)
            if attempt < attempts - 1:
                await asyncio.sleep(delay)
            last_exc = httpx.HTTPStatusError(
                f'SEC returned {response.status_code}', request=response.request, response=response
            )
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            if status not in (429, 503):
                raise
            if attempt < attempts - 1:
                await asyncio.sleep(min(8.0, 0.75 * (2 ** attempt)))
    if last_exc:
        raise last_exc
    raise RuntimeError('SEC request failed without a response')


class SecInsidersFeed(Feed):
    name = 'insiders'

    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    async def fetch(self, tickers: dict[str, str] | None = None) -> FeedResult:
        headers = {
            'User-Agent': settings.sec_user_agent,
            'Accept-Encoding': 'gzip, deflate',
            'Accept': 'application/json, application/xml, text/xml, */*',
        }
        try:
            universe_response = await sec_get(
                self.client,
                'https://www.sec.gov/files/company_tickers.json',
                headers,
            )
            universe = {}
            for value in universe_response.json().values():
                ticker = str(value.get('ticker', '')).upper()
                if valid_symbol(ticker):
                    meta = {
                        'cik': str(value['cik_str']).zfill(10),
                        'title': value.get('title'),
                    }
                    for alias in symbol_aliases(ticker):
                        universe[alias] = meta

            wanted = [
                t.upper()
                for t in (tickers or {})
                if valid_symbol(t)
            ]
            items = []
            errors = []

            for requested_ticker in wanted:
                meta = universe.get(requested_ticker) or universe.get(requested_ticker.replace('.', '-'))
                if not meta:
                    logger.info('SEC ticker not found in company_tickers: %s', requested_ticker)
                    continue

                try:
                    submissions_url = f"https://data.sec.gov/submissions/CIK{meta['cik']}.json"
                    sr = await sec_get(self.client, submissions_url, headers)
                    recent = sr.json().get('filings', {}).get('recent', {})
                except Exception as exc:
                    errors.append(f'{requested_ticker} submissions: {exc}')
                    logger.warning('SEC submissions failed for %s: %s', requested_ticker, exc)
                    continue

                count = 0
                forms = recent.get('form', [])
                for i, form in enumerate(forms):
                    if form != '4' or count >= 8:
                        continue
                    accession = recent.get('accessionNumber', [''])[i]
                    filed = recent.get('filingDate', [''])[i]
                    primary = recent.get('primaryDocument', [''])[i]
                    if not accession or not primary:
                        continue

                    archive = (
                        f"https://www.sec.gov/Archives/edgar/data/{int(meta['cik'])}/"
                        f"{accession.replace('-', '')}/{primary}"
                    )
                    try:
                        fr = await sec_get(self.client, archive, headers)
                        root = ET.fromstring(fr.content)
                    except Exception as exc:
                        errors.append(f'{requested_ticker} {accession}: {exc}')
                        logger.warning('SEC Form 4 parse/fetch failed for %s %s: %s', requested_ticker, accession, exc)
                        count += 1
                        continue

                    issuer_symbol = (text(root, './/issuerTradingSymbol') or requested_ticker).upper()
                    if not valid_symbol(issuer_symbol):
                        logger.info('SEC Form 4 rejected malformed issuer symbol %r for %s', issuer_symbol, requested_ticker)
                        count += 1
                        continue

                    # Keep the application's requested ticker as canonical when SEC
                    # uses the equivalent dot/hyphen spelling (e.g. BRK.B / BRK-B).
                    canonical_ticker = requested_ticker if symbol_aliases(issuer_symbol) & symbol_aliases(requested_ticker) else issuer_symbol

                    owner = root.find('.//reportingOwner')
                    owner_name = text(owner, './/rptOwnerName') if owner is not None else None
                    role = (text(owner, './/officerTitle') if owner is not None else None)
                    if not role and owner is not None and text(owner, './/isDirector') == '1':
                        role = 'Director'

                    transaction_count = 0
                    for tx in root.findall('.//nonDerivativeTransaction'):
                        code = text(tx, './/transactionCoding/transactionCode')
                        if code not in {'P', 'S'}:
                            continue
                        action = 'buy' if code == 'P' else 'sell'
                        shares_raw = text(tx, './/transactionAmounts/transactionShares/value')
                        price_raw = text(tx, './/transactionAmounts/transactionPricePerShare/value')
                        try:
                            shares = float(shares_raw) if shares_raw else None
                        except (TypeError, ValueError):
                            shares = None
                        try:
                            price = float(price_raw) if price_raw else None
                        except (TypeError, ValueError):
                            price = None
                        value = shares * price if shares is not None and price is not None else None
                        transaction_id = f'{canonical_ticker}:{accession}:{transaction_count}'
                        items.append({
                            'id': hashlib.sha256(transaction_id.encode()).hexdigest()[:20],
                            'ticker': canonical_ticker,
                            'company': meta.get('title'),
                            'insider_name': owner_name or 'Unavailable in filing',
                            'role': role,
                            'action': action,
                            'shares': shares,
                            'dollar_value': value,
                            'filing_date': filed,
                            'source_url': archive,
                            'feed_mode': 'live',
                        })
                        transaction_count += 1
                    count += 1

            if items:
                return FeedResult(items)
            if errors:
                return FeedResult([], ' | '.join(errors[:3]))
            return FeedResult([])
        except Exception as exc:
            logger.exception('SEC insiders feed failed')
            return FeedResult([], str(exc))
