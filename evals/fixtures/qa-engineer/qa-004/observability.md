# Observability bundle - qa-004

## Environment
- URL: http://localhost:3000/contact
- Auth: not required for this route
- Browser: Chromium via Playwright

## DOM snapshot (form rendered)

```
@e1 <form>
  @e2 <input name="name" value="">
  @e3 <input name="email" type="email" value="">
  @e4 <textarea name="message"></textarea>
  @e5 <button type="submit">Send</button>
</form>
```

## Interaction 1: submit empty form

After clicking @e5 with all fields empty:

```
@e6 <div class="error">name is required</div>
@e7 <div class="error">email is required</div>
@e8 <div class="error">message is required</div>
```

Three validation error messages rendered as expected. No network request
was made (validation short-circuited).

## Interaction 2: submit filled form

Filled @e2="Alice", @e3="alice@example.com", @e4="hello", clicked @e5.

## Console log

```
[log] submit handler fired
[error] POST http://localhost:3000/api/contact 500 (Internal Server Error)
[error] Unhandled promise rejection: Error: request failed
```

2 errors captured.

## Network log

```
200 GET  /contact                           (initial load)
500 POST /api/contact                       (body: {"name":"Alice","email":"alice@example.com","message":"hello"})
     response body: {"error":"ReferenceError: db is not defined"}
```

## Test runner output

```
$ pnpm test src/pages/__tests__/contact.test.tsx
PASS  src/pages/__tests__/contact.test.tsx
  Contact
    ok renders form fields
    ok shows validation errors on empty submit

$ pnpm test src/pages/api/__tests__/contact.test.ts
FAIL  src/pages/api/__tests__/contact.test.ts
  POST /api/contact
    FAIL persists a contact entry
      ReferenceError: db is not defined
        at handler (src/pages/api/contact.ts:7:3)
Tests: 1 failed, 2 passed, 3 total
```

## Screenshots

- /tmp/qa_20260420_131700_contact_form_initial.png
- /tmp/qa_20260420_131702_contact_validation_errors.png
- /tmp/qa_20260420_131705_contact_submit_failure.png - success banner NOT shown
