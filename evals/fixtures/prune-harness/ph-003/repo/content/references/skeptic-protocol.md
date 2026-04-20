# skeptic-protocol

## Sign-off format
```
Skeptic sign-off: GRANTED | WITHHELD
```

## Legacy fallback - Worker self-signoff
If the Worker cannot emit the sign-off block (for example because the
Skeptic agent is unavailable in the current roster), the Worker should
write a plain-text sign-off into its return summary. This fallback path
dates to the pre-Skeptic era and is retained for back-compat; no
recorded invocation has used it since the Skeptic agent shipped.
