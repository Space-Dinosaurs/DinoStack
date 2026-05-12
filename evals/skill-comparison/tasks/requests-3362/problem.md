# Task: requests-3362

**SWE-bench instance ID:** `psf__requests-3362`
**Difficulty:** single-file
**Repository:** https://github.com/psf/requests
**Base commit:** `37a0b4a3a7e350d8b1c9f83fce83e6c56a5b6a5b`

## Problem description

`PreparedRequest.prepare_url` mishandles URLs that contain a `#` fragment
when the URL also has a query string.  The fragment is percent-encoded and
appended to the query string instead of being kept as the URL fragment
component, breaking round-trip serialisation:

```
Input:  http://example.com/path?q=1#section
Output: http://example.com/path?q=1%23section   (wrong)
Expected: http://example.com/path?q=1#section
```

## Reproduction

```python
import requests
r = requests.Request("GET", "http://example.com/path?q=1#section")
p = r.prepare()
assert "#section" in p.url    # AssertionError: fragment was encoded into query
```

## Expected behaviour

`PreparedRequest.url` should preserve the fragment component unchanged.
Fragments are not sent to the server (per RFC 7230) but must survive
round-trip serialisation so that logging, redirect handling, and user
inspection see the correct URL.

## Held-out test reference

`tests/test_requests.py` (from fix commit
`9a1c13d21e04264f9abb0cfbf7b7bf05e1ea2ca6`).

The new test verifies that:
- A URL with a fragment is not percent-encoded.
- A URL without a fragment is unaffected.
- A URL with both a query string and a fragment preserves both.

## Constraints for the fix

- Modify only `requests/models.py`.
- Do not change the public `prepare_url` signature.
- All existing `test_requests.py` tests must pass.
