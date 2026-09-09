from app.services.scoring import Signal,money_match

def test_one_source_caps_at_33(): assert money_match([Signal('news','bullish',1)])==33

def test_two_agree_cap_67(): assert money_match([Signal('news','bullish',1),Signal('insiders','bullish',1)])==67

def test_three_agree_reaches_100(): assert money_match([Signal('news','bullish',1),Signal('insiders','bullish',1),Signal('congress','bullish',1)])==100

def test_stale_does_not_vote_or_cover(): assert money_match([Signal('news','bullish',1),Signal('insiders','bullish',1,stale=True)])==33

def test_neutral_fired_counts_coverage_but_contributes_zero(): assert money_match([Signal('news','bullish',1),Signal('insiders','neutral',1)])==33

def test_disagreement_reduces_score(): assert money_match([Signal('news','bullish',1),Signal('insiders','bearish',1)])==0
