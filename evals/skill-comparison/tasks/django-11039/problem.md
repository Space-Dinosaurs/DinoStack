# Task: django-11039

**SWE-bench instance ID:** `django__django-11039`
**Difficulty:** multi-file
**Repository:** https://github.com/django/django
**Base commit:** `2f037b49b4b93e4a2a76f41d77c0d0d2c58e9f4a`

## Problem description

Pickling a `Q` object that contains a subquery fails with:

```
AttributeError: 'NoneType' object has no attribute 'compiler'
```

When `Q.__reduce__` is called, it invokes `sql_with_params()` on the
contained queryset to produce a string representation.  This calls into
the SQL compiler before the queryset is fully set up in the new process,
causing a null-pointer-style failure.

The fix requires changes in two places:
1. `django/db/models/query_utils.py` - fix `Q.__reduce__` to defer SQL
   compilation rather than calling it eagerly.
2. `django/db/models/sql/query.py` - ensure `resolve_lookup_value` handles
   a subquery that arrives from an unpickled Q correctly.

## Reproduction

```python
import pickle
from django.db.models import Q, Subquery
from myapp.models import Author, Book

sq = Subquery(Author.objects.values("id")[:1])
q = Q(author_id__in=sq)
data = pickle.dumps(q)
q2 = pickle.loads(data)   # AttributeError
```

## Expected behaviour

`pickle.loads(pickle.dumps(Q(...subquery...)))` should round-trip
correctly and produce a `Q` object that generates the same SQL.

## Held-out test references

- `tests/queryset_pickle/tests.py` (pickle round-trip test)
- `tests/queries/test_q.py` (Q object SQL generation after unpickle)

Both from fix commit `b7c3a6e9f2d1e8a4c5f7b9d2e6c4a8b1f3e7d9a2`.

## Constraints for the fix

- Modify `django/db/models/query_utils.py` and
  `django/db/models/sql/query.py` only.
- Do not change the public Q or Subquery API.
- All existing tests in both test files must pass.
