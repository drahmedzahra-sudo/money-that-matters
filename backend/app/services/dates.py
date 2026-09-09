from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

FORMATS = ["%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"]

def parse_date(value: str) -> datetime:
    value = (value or "").strip()
    if not value:
        raise ValueError("empty date")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        pass
    for fmt in FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"unsupported date format: {value}")
