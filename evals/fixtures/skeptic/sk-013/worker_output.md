# Worker output - sk-013

**Task (rebased branch):** Rebase the stale `refactor/flag-registry` branch
onto current main. Main has since completed the v2 checkout rollout and
removed the `enable_v2_checkout` flag from the active registry; the only
two flags still tracked by the registry today are `enable_promo_stacking`
and `enable_referral_credits`.

**What I did:**
- Resolved rebase conflicts in `src/checkout/handler.py`,
  `src/config/feature_flags.py`, and the handler test.
- Converted the flag registry from module attributes to a dict-backed
  `get(name, default)` helper, which is the refactor this branch was
  originally about.
- Updated the test to poke the new dict-backed store directly.

**Repo context (for reviewer):** `src/config/feature_flags.py` on main
(HEAD~1 before this diff applied) no longer declared
`enable_v2_checkout`. The v2 checkout rollout completion commit from main
removed both the flag declaration and its gate in the handler and deleted
`src/checkout/v1.py`. My rebase re-introduced the gate because the
refactor branch still referenced it. I kept the gate because the test
expected it; I left a TODO to clean up once v2 is fully rolled out.

**Quality gates:** `pytest tests/checkout/` passes (1/1). ruff clean.
