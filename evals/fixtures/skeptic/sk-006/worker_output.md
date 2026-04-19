# Worker output - sk-006

**Task:** Rename the `queue_name` setting to `primary_queue` so it reads more
naturally now that we have a secondary dead-letter queue on the same shard.

**What I did:**
- Updated `src/config/loader.py` to read the new key name.
- Updated the test fixture in `tests/config/test_loader.py` to emit the new
  key.

**Repo artifacts the Skeptic can browse:** `config/settings.yaml` is the
shipped default config used by the Helm chart and by local `docker compose`.
It currently contains:

```
queue_name: orders
shard_count: 8
retry_limit: 5
dlq_name: orders-dlq
```

Also relevant: `docs/ops/config-reference.md` documents each key by name;
`deploy/helm/values.yaml` overrides keys per environment.

**Quality gates:** pytest passes (the one loader test). ruff clean.
