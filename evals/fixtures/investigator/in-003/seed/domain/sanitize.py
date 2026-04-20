"""Sanitization helpers."""

import re

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html_tags(text):
    """Remove anything that looks like an HTML tag."""
    return _TAG_RE.sub("", text)
