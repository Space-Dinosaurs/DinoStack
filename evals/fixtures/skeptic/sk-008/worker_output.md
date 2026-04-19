# Worker output - sk-008

**Task:** Send a welcome email when a new user signs up. The email must not
block the signup response; a slow SMTP provider or a transient mail outage
should not cause the signup HTTP call to time out.

**What I did:**
- Added `sendWelcomeEmail(userId, email)` to `src/services/mail.ts`.
- Invoked it from `handleSignup` after `createUser` resolves, without
  awaiting the promise, so the HTTP response returns immediately.

**Repo context:** The project runs on Node 20 under PM2. There is a global
error reporter wired in `src/bootstrap.ts` (`Sentry.init(...)`), and an
`errorLogger` middleware registered last on the Express app. Neither of
those observes non-awaited promises in request handlers. The existing
`sendOrderConfirmation` is called with `await` inside a Bull queue worker,
not fire-and-forget.

**Quality gates:** `npm test` passes (37 tests). `tsc --noEmit` clean.
`eslint` clean.
