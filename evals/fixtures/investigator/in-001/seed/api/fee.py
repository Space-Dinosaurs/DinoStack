"""Fee computation for customer invoices."""

from typing import Optional

from api.tiers import TIER_RATES, DEFAULT_RATE


def compute_fee(customer) -> float:
    """Return the fee for `customer`.

    If the customer has no tier assigned (tier is None), fall back to the
    DEFAULT_RATE constant rather than raising. This keeps the invoice
    pipeline from blowing up on freshly-onboarded customers whose tier has
    not yet been propagated from the CRM.
    """
    tier: Optional[str] = customer.tier
    if tier is None:
        rate = DEFAULT_RATE
    else:
        rate = TIER_RATES.get(tier, DEFAULT_RATE)
    return round(customer.subtotal * rate, 2)
