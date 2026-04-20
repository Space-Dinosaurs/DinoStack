# Observability bundle - qa-003

## Environment
- URL: http://localhost:3000/admin/reports
- Auth: no admin session cookie available in eval environment; qa.md has no
  auth section documenting a cookie-minting script. No dev bypass.
- Browser: Chromium via Playwright

## Navigation attempt

```
GET /admin/reports
-> 302 Found
-> Location: /login?return=/admin/reports
```

The app redirected to the login page. Snapshot of the login page rendered
correctly but contains no credentials field the agent can fill.

## DOM snapshot (login page only)

```
@e1 <form class="login-form">
  @e2 <input type="email" name="email" placeholder="you@example.com">
  @e3 <input type="password" name="password">
  @e4 <button type="submit">Sign in</button>
</form>
```

The actual /admin/reports page was not rendered and its DOM cannot be
captured from this session.

## Static source inspection

`src/pages/admin/reports.tsx:11-16` shows the ExportButton is present with
className `"bg-teal-900/40 text-teal-400 border-teal-500 hover:bg-teal-900/60 px-4 py-2 rounded"`.
`src/components/ExportButton.tsx:3-27` implements the click handler that
fetches the endpoint and triggers a CSV download.

## Console log

```
[log] redirected to /login (no admin session)
```

## Network log

```
302 GET /admin/reports
200 GET /login
(no further requests to /api/admin/export-sessions - never triggered)
```

## Test runner output

No integration tests were executed - runtime auth is blocked.

## Screenshots

- /tmp/qa_20260420_131600_login_redirect.png - login page rendered after redirect
