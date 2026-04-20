"""Comment domain logic."""

from domain.sanitize import strip_html_tags
from infra.db import insert_row


def store_comment(user_id, body):
    # Strip any HTML before persistence. We store plaintext; rendering
    # layer will escape on read.
    cleaned = strip_html_tags(body)
    row = {"user_id": user_id, "body": cleaned}
    return insert_row("comments", row)
