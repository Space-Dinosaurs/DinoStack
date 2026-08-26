<!-- corpora: minimal medium full -->
## Cross-session loop resume

Long-running `/ds-implement-ticket` loops survive via a per-ticket `.agentic/loop-state-<LOOP_KEY>.json` written at every phase transition (superseding the single legacy `.agentic/loop-state.json`, which is still read and adopted when present); read `content/references/cross-session-loop-resume.md` §Cross-session loop resume at session start when any loop-state file exists.
