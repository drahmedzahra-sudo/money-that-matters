from app.services.dates import parse_date

def test_iso_offset(): assert parse_date('2026-09-09T12:30:00+03:00').tzinfo is not None

def test_plain_iso(): assert parse_date('2026-09-09').year==2026

def test_mdy(): assert parse_date('09/09/2026').day==9


from datetime import datetime, timezone, timedelta
from app.services.dates import utc_age

def test_utc_age_accepts_naive_datetime():
    updated = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
    age = utc_age(updated)
    assert timedelta(minutes=4) < age < timedelta(minutes=6)

def test_utc_age_accepts_aware_datetime():
    updated = datetime.now(timezone.utc) - timedelta(minutes=5)
    age = utc_age(updated)
    assert timedelta(minutes=4) < age < timedelta(minutes=6)
