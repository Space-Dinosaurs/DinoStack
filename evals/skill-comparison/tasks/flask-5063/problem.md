# Task: flask-5063

**SWE-bench instance ID:** `pallets__flask-5063`
**Source:** princeton-nlp/SWE-bench_Lite (test split)
**Freeze date:** 2026-05-12
**Difficulty:** multi-file
**Repository:** https://github.com/pallets/flask
**Base commit:** `182ce3dd15dfa3537391c3efaf9c3ff407d134d4`

## Problem description

The `flask routes` CLI command shows all registered routes but provides no
way to see which subdomain or host each route is assigned to.

```
$ flask routes
Endpoint  Methods  Rule
--------  -------  ------
index     GET      /
```

When an application uses subdomain routing (`subdomain="api"`) or host
matching (`host="api.example.com"`), that information is absent from the
routes table, making it impossible to diagnose routing issues from the CLI.

The fix requires adding domain/subdomain columns to the routes table output
in `src/flask/cli.py`, including the new columns in the display and tests.

## Expected behaviour

`flask routes` should display subdomain and host columns when any route
uses subdomain or host-based routing, making the full routing configuration
visible.

## Held-out test references

- `tests/test_cli.py`

Tests `TestRoutes::test_subdomain` and `TestRoutes::test_host` must
transition from fail to pass.
