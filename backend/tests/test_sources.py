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

def test_gdelt_empty_response_is_explicit():
    from app.feeds.news import parse_gdelt_payload
    class R:
        text = ''
        def json(self): raise ValueError('empty')
    try:
        parse_gdelt_payload(R())
    except ValueError as exc:
        assert 'empty response' in str(exc)
    else:
        raise AssertionError('Expected explicit empty-response error')
