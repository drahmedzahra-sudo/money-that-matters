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
