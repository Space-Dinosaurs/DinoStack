# Task: requests-3362

**SWE-bench instance ID:** `psf__requests-3362`
**Source:** princeton-nlp/SWE-bench_Lite (test split)
**Freeze date:** 2026-05-12
**Difficulty:** single-file
**Repository:** https://github.com/psf/requests
**Base commit:** `36453b95b13079296776d11b09cab2567ea3e703`

## Problem description

`iter_content(decode_unicode=True)` returns `bytes` instead of `str` when
the response has no declared encoding, even though `decode_unicode=True`
explicitly requests string output.

```python
import requests
r = requests.get("https://httpbin.org/json")
chunk = next(r.iter_content(16 * 1024, decode_unicode=True))
# chunk is bytes, not str, when Content-Type has no charset
```

The fix is in `requests/utils.py` in the `stream_decode_response_unicode`
helper, which fails to fall back to a default encoding when the response
charset is absent.

## Expected behaviour

`iter_content(decode_unicode=True)` should always return `str` objects when
`decode_unicode=True`, falling back to a sensible default encoding when the
response does not declare one.

## Held-out test references

- `tests/test_requests.py`

Test `TestRequests::test_response_decode_unicode` must transition from fail
to pass.
