"""Explicit date formats only: never infer a missing year or swap day/month."""
import re
from datetime import date

_MONTHS = {name.lower(): index for index, name in enumerate(
    ['January','February','March','April','May','June','July','August','September','October','November','December'], 1)}
_MONTHS.update({name[:3]: number for name, number in list(_MONTHS.items())})


def normalize_date(value: str) -> str:
    value = value.strip()
    iso = re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})', value)
    us = re.fullmatch(r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', value)
    named = re.fullmatch(r'([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(\d{4})', value, re.I)
    day_first = re.fullmatch(r'(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([A-Za-z]+)\.?[,]?\s+(\d{4})', value, re.I)
    if iso:
        year, month, day = map(int, iso.groups())
    elif us:
        month, day, year = map(int, us.groups())
    elif named and named[1].lower() in _MONTHS:
        month, day, year = _MONTHS[named[1].lower()], int(named[2]), int(named[3])
    elif day_first and day_first[2].lower() in _MONTHS:
        month, day, year = _MONTHS[day_first[2].lower()], int(day_first[1]), int(day_first[3])
    else:
        raise ValueError('Enter a complete date as MM/DD/YYYY (month/day/year), YYYY-MM-DD, or Month Day, Year. Include the four-digit year.')
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        raise ValueError('That date does not exist. Check the month, day and four-digit year; use MM/DD/YYYY.') from None
