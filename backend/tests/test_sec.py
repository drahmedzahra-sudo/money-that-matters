from app.feeds.sec import valid_symbol, symbol_aliases


def test_sec_symbol_validation():
    assert valid_symbol('AAPL')
    assert valid_symbol('BRK.B')
    assert valid_symbol('BRK-B')
    assert not valid_symbol('TOO_LONG7')
    assert not valid_symbol('bad symbol')


def test_sec_symbol_aliases():
    assert symbol_aliases('BRK.B') == {'BRK.B', 'BRK-B'}
    assert symbol_aliases('AAPL') == {'AAPL'}
