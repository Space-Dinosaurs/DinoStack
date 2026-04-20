"""HTTP handlers. Entry point for user-submitted comment text."""

from web.forms import parse_comment_form
from domain.comments import store_comment


def post_comment(request):
    form = parse_comment_form(request.body)
    body = form["body"]
    return store_comment(request.user_id, body)
