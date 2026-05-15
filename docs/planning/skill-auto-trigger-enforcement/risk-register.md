# Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Kimi stdout not routed to agent context | Medium | High - feature silent for Kimi | Worker verifies Kimi docs; fallback to stderr with comment |
| OpenCode `session.created` event unavailable | Medium | Medium - fall back to `session.idle` guard | Worker checks SDK types; fallback specified in plan |
| `ae_write_config` key-destruction on re-run (open(..., "w") overwrites entire JSON) | High if not fixed | High - silently resets user's skill_auto_load preference to false | Fixed: all 8 install scripts use read-modify-write (json.load + merge + write); concurrent install race is negligible (single-user flow) |
| `.claude/build.sh` in Unit 11 clobbers in-flight changes | High if parallelized | High | Unit 11 declared sequential tail; orchestration enforces this |
| Cursor existing users don't re-run install | High | Low - only affects Cursor users; .mdc rules already load methodology | Install notice added; Cursor methodology already globally loaded |
| Pi/OMP enforcement is probabilistic (SKILL.md content only) | N/A | Low - Pi/OMP have no hook mechanism; best available option | Documented known gap |
