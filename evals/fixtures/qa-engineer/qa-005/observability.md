# Observability bundle - qa-005

## Environment
- URL: http://localhost:3000/account/billing
- Auth: NO session cookie available in eval environment. Route is behind
  an auth gate. There is NO qa.md in this project, so no documented
  cookie-minting script or dev bypass exists.
- Browser: Chromium via Playwright

## Navigation attempt

```
GET /account/billing
-> 302 Found
-> Location: /login?return=/account/billing
```

Redirected to login. Cannot proceed past this point without credentials.
The entire feature (Upgrade button, Stripe redirect, webhook-driven plan
flip) is runtime-gated behind auth and a live Stripe integration. No
criterion can be exercised without a seeded admin/user session.

## DOM snapshot (login page only, for completeness)

```
@e1 <form class="login-form">
  @e2 <input type="email" name="email">
  @e3 <input type="password" name="password">
  @e4 <button type="submit">Sign in</button>
</form>
```

No path exists to the billing page in this environment.

## Console log

```
[log] redirected to /login (no session)
```

## Network log

```
302 GET /account/billing
200 GET /login
(no requests to /api/stripe/checkout or /api/stripe/webhook)
```

## Test runner output

No automated tests could be run against the flow - webhook path requires
Stripe CLI + live test keys.

## Screenshots

- /tmp/qa_20260420_131800_login_redirect.png - login page rendered

## Notes

No qa.md exists. No `scripts/mint-qa-session.ts`, no documented dev
bypass. Per the hard rule in content/agents/qa-engineer.md section
"Auth handling", a UI-rendering runtime feature behind an auth wall
with no documented bypass must return BLOCKED.
