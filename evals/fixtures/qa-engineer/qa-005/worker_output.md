# Worker output - qa-005

**Task:** Stripe Checkout upgrade flow.

**What I did:**
- Added `/account/billing` page with Upgrade button.
- Server-side `/api/stripe/checkout` creates Stripe Checkout session.
- Server-side `/api/stripe/webhook` flips `accounts.plan` to `pro` on
  `checkout.session.completed`.
- Uses env vars `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`, `STRIPE_WEBHOOK_SECRET`,
  `APP_URL`.

**Quality gates:** tsc clean, lint clean. End-to-end flow requires live
Stripe test keys and webhook forwarding.
