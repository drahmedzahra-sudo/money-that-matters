from app.services.relevance import host_allowed,MARKET_ALLOWED,EGYPT_ALLOWED,market_subject_ok,egypt_subject_ok

def test_host_boundary():
    assert host_allowed('https://www.reuters.com/a',MARKET_ALLOWED)
    assert not host_allowed('https://notreuters.com/a',MARKET_ALLOWED)
    assert not host_allowed('https://reuters.com.spam.tld/a',MARKET_ALLOWED)

def test_market_relevance():
    assert market_subject_ok('Apple AAPL raises guidance','AAPL','Apple')
    assert market_subject_ok('Federal Reserve interest rate decision')
    assert not market_subject_ok('War update with no market subject')

def test_egypt_relevance():
    assert egypt_subject_ok('Egypt stocks rally')
    assert egypt_subject_ok('البورصة المصرية ترتفع',native=True)
    assert not egypt_subject_ok('International football results',native=False)


def test_egypt_official_egx_feed_is_present():
    from app.feeds.news import EgyptEGXFeed
    assert EgyptEGXFeed.URL.startswith("https://beta.egx.com.eg/")

def test_egypt_uses_official_egx_source_in_sync():
    from pathlib import Path
    main=(Path(__file__).parents[1]/"app"/"main.py").read_text()
    assert "EgyptEGXFeed" in main
    assert "Egyptian Exchange (EGX)" in main and "Ahram Online Markets & Companies" in main
