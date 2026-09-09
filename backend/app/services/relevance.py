from urllib.parse import urlparse

MARKET_ALLOWED = {"reuters.com", "cnbc.com", "bloomberg.com", "wsj.com", "sec.gov"}
EGYPT_ALLOWED = {
    "reuters.com", "bloomberg.com", "cnbc.com", "wsj.com", "zawya.com", "apnews.com",
    "enterprise.news", "mubasher.info", "almalnews.com", "alborsaanews.com", "masrawy.com",
    "shorouknews.com", "ahram.org.eg", "egx.com.eg", "cbe.org.eg", "capmas.gov.eg"
}

MARKET_ANCHORS = ["s&p", "nasdaq", "dow jones", "dow", "sector", "central bank", "interest rate", "rates", "tariff", "trade decision", "earnings", "guidance", "forecast"]
EGYPT_NATIVE_ANCHORS = ["اقتصاد", "بنوك", "أسهم", "البورصة", "الجنيه", "تضخم", "فائدة", "مصر", "egx", "بنك مركزي", "سوق المال"]


def host_allowed(url: str, allowed: set[str]) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return any(host == d or host.endswith("." + d) for d in allowed)


def market_subject_ok(text: str, ticker: str | None = None, company: str | None = None) -> bool:
    hay = text.lower()
    if ticker and _whole_word(ticker.lower(), hay):
        return True
    if company and company.lower() in hay:
        return True
    return any(x in hay for x in MARKET_ANCHORS)


def egypt_subject_ok(text: str, native: bool = False) -> bool:
    hay = text.lower()
    if "egypt" in hay or "egx" in hay or "مصر" in text or "البورصة" in text:
        return True
    return native and any(x in text for x in EGYPT_NATIVE_ANCHORS)


def _whole_word(token: str, text: str) -> bool:
    import re
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])", text, re.I))
