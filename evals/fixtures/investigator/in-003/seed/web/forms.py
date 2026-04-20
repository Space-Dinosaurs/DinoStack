"""Form parsing. Extracts fields from request bodies.

Note: this module does NOT sanitize field values. It only trims outer
whitespace and enforces a max length. Escaping is left to the domain layer.
"""

MAX_COMMENT_LEN = 4096


def parse_comment_form(body_bytes):
    raw = body_bytes.decode("utf-8", errors="replace")
    fields = {}
    for part in raw.split("&"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        fields[k] = v.strip()
    if len(fields.get("body", "")) > MAX_COMMENT_LEN:
        fields["body"] = fields["body"][:MAX_COMMENT_LEN]
    return fields
