# Worker output - sk-002

**Task:** Add a `GET /files/{name}` endpoint that serves files from the
configured `FILE_STORE_DIR` to authenticated users.

**What I did:**
- Added `src/api/files.py` with a new route handler `download_file`.
- Used `os.path.join(FILE_STORE_DIR, name)` to resolve the target path and
  streamed the file back with `FileResponse`.
- Added one integration test that downloads a seeded `readme.txt`.

**Quality gates:** pytest passes. Auth middleware fires before the handler, so
only logged-in users reach this code path.
