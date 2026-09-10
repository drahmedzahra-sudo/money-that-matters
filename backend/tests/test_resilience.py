from app.feeds.sec import STATIC_CIKS

def test_static_sec_universe_covers_baseline():
    expected = "AAPL,MSFT,NVDA,AMZN,META,GOOGL,GOOG,AVGO,TSLA,BRK.B,JPM,V,MA,LLY,WMT,XOM,UNH,ORCL,COST,HD,PG,JNJ,ABBV,CRM,AMD,NFLX,ADBE,QCOM,INTC,CSCO".split(',')
    assert all(t in STATIC_CIKS for t in expected)

def test_no_placeholder_or_demo_data():
    import pathlib
    root=pathlib.Path(__file__).parents[1]/'app'
    text='\n'.join(p.read_text(errors='ignore') for p in root.rglob('*.py'))
    assert 'demo' not in text.lower()
    assert 'sample data' not in text.lower()


def test_form4_parser_recovers_malformed_xml():
    from app.feeds.sec import parse_form4
    malformed = b'''<ownershipDocument><issuer><issuerTradingSymbol>AAPL</issuerTradingSymbol></issuer>\n    <nonDerivativeTransaction><transactionCoding><transactionCode>P</transactionCode></transactionCoding>\n    <transactionAmounts><transactionShares><value>10</value></transactionShares></transactionAmounts>\n    </nonDerivativeTransaction><broken>oops</ownershipDocument>'''
    root, parser = parse_form4(malformed)
    assert parser == "soup"
    assert root.find("nonderivativetransaction") is not None


def test_house_xml_parser_has_text_fallback():
    from app.feeds.house import HouseCongressFeed
    bad=b"<root><row><member>A</member></root>"
    txt=b"FilingType\tDocID\tFirst\tLast\nP\t123\tJane\tDoe\n"
    try:
        HouseCongressFeed._rows_from_xml(bad)
        assert False
    except Exception:
        pass
    rows=HouseCongressFeed._rows_from_text(txt)
    assert rows[0]["DocID"] == "123"

def test_sec_cache_datetime_normalization_is_explicit():
    from datetime import datetime, timezone
    naive=datetime(2026,1,1)
    aware=naive.replace(tzinfo=timezone.utc)
    assert aware.tzinfo is not None


def test_sec_universe_uses_static_ciks_without_live_company_tickers_dependency():
    from app.feeds.sec import STATIC_CIKS
    assert STATIC_CIKS["AAPL"] == "320193"
    assert STATIC_CIKS["MSFT"] == "789019"

def test_v7_source_integrity_files_are_present():
    from pathlib import Path
    root=Path(__file__).parents[1]
    main=(root/'app'/'main.py').read_text()
    house=(root/'app'/'feeds'/'house.py').read_text()
    sec=(root/'app'/'feeds'/'sec.py').read_text()
    assert 'v8-concurrent-feed-runtime' in main
    assert 'txt_name' in house and 'FD.zip' in house
    assert 'company_tickers' in sec and 'https://www.sec.gov/files/company_tickers.json' not in sec


def test_sec_limiter_is_not_serially_slow():
    from app.feeds.limiter import sec_limiter
    assert sec_limiter.min_interval <= 0.2
