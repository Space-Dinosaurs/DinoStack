"""Currency formatting helper."""


def format_currency(amount_cents, currency="USD"):
    """Return a display string like '$12.34' or '12,34 EUR'.

    Supports USD (prefix, dot decimal) and EUR (suffix, comma decimal).
    Falls back to an ISO-code suffix for other currencies.
    """
    if amount_cents < 0:
        sign = "-"
        amount_cents = -amount_cents
    else:
        sign = ""
    whole = amount_cents // 100
    frac = amount_cents % 100
    if currency == "USD":
        return f"{sign}${whole}.{frac:02d}"
    if currency == "EUR":
        return f"{sign}{whole},{frac:02d} EUR"
    return f"{sign}{whole}.{frac:02d} {currency}"
