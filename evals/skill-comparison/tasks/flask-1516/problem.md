# Task: flask-1516

**SWE-bench instance ID:** `pallets__flask-1516`
**Difficulty:** single-file
**Repository:** https://github.com/pallets/flask
**Base commit:** `4b8f5e8b2a4a53a5c9d2e6f4e8a6f4c3e2d5a8b1`

## Problem description

`Flask.make_response` raises `ValueError: too many values to unpack`
when a view function returns a `(response, Headers)` tuple where the
second element is a `werkzeug.datastructures.Headers` instance instead
of a plain `dict`.

The implementation checks `isinstance(rv[1], dict)` to detect response
headers, but `Headers` is not a subclass of `dict`, so the check fails
and the code falls into the wrong branch.

## Reproduction

```python
from flask import Flask
from werkzeug.datastructures import Headers

app = Flask(__name__)

@app.route("/")
def index():
    h = Headers()
    h["X-Custom"] = "hello"
    return "ok", h   # raises ValueError inside make_response

with app.test_client() as c:
    c.get("/")   # ValueError
```

## Expected behaviour

`make_response` should accept a `Headers` object in the same position as
a plain `dict` and use its key-value pairs as response headers.

## Held-out test reference

`tests/test_app.py` (from fix commit
`9c7b1d6e4f5a8c2e3d7b9a1c5e3f6a2d8b4c7e1f`).

The new test:
1. Creates a view returning `(body, Headers(...))`.
2. Asserts the response has the expected header value.
3. Asserts no `ValueError` is raised.

## Constraints for the fix

- Modify only `src/flask/app.py`.
- Do not change `make_response`'s public signature.
- All existing `test_app.py` tests must pass.
