from app.services.dates import parse_date

def test_iso_offset(): assert parse_date('2026-09-09T12:30:00+03:00').tzinfo is not None

def test_plain_iso(): assert parse_date('2026-09-09').year==2026

def test_mdy(): assert parse_date('09/09/2026').day==9
