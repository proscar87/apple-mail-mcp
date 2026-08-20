"""Verify a saved reply's new body landed outside Mail's quoted original.

`reply_to_email` (see `compose.py`) inserts the new reply body via a blind
clipboard paste into Mail's native reply composer, which already contains
the quoted original thread. That paste is not verified by reading back
`content of replyMessage` -- Mail's GUI editor buffer is decoupled from that
scriptable property, so a read-back there always reports the pre-paste
value even after a successful paste (see the comment above the keystroke
step in `compose.py`).

This module verifies the *saved* draft instead, by reading its raw RFC 822
source (via the existing `get_email_source` tool) after the paste has
already landed on disk. If the new body ends up inside Mail's quoted-original
container -- HTML `<blockquote type="cite">` or a plain-text `>`-quoted
block -- instead of above it, this catches that rather than the tool
reporting success on text presence alone (#71).

Heuristic, not exact: substring matching after whitespace/tag normalization
can produce a false negative if Mail's own text engine reformats the pasted
text (autocorrect, smart-quote substitution) before saving. That is a
narrower failure mode than the one this module closes -- a wrong verdict
that still gets caught by *no* match at all is safer than the previous
behaviour, which never checked in the first place.
"""

import html
import re
from email import message_from_string, policy
from typing import Optional, Tuple

_CITE_BLOCKQUOTE_RE = re.compile(
    r'<blockquote[^>]*\btype\s*=\s*["\']cite["\'][^>]*>', re.IGNORECASE
)
_TAG_RE = re.compile(r"<[^>]+>")


def _extract_bodies(raw_source: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (html_body, text_body) from an RFC 822 source string.

    Prefers the first `text/html` and first `text/plain` part found while
    walking the message (covers both `multipart/alternative` and a bare
    single-part message of either type).
    """
    msg = message_from_string(raw_source, policy=policy.default)
    html_body: Optional[str] = None
    text_body: Optional[str] = None

    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        content_type = part.get_content_type()
        if content_type == "text/html" and html_body is None:
            html_body = part.get_content()
        elif content_type == "text/plain" and text_body is None:
            text_body = part.get_content()

    return html_body, text_body


def _html_before_quote(html_body: str) -> str:
    """Return the HTML preceding Mail's quoted-original blockquote, if any.

    Mail's reply composer places new content entirely above the quote
    block, never interleaved, so "before the first cite-blockquote's open
    tag" is the new-content region for a well-formed reply.
    """
    match = _CITE_BLOCKQUOTE_RE.search(html_body)
    return html_body if match is None else html_body[: match.start()]


def _text_before_quote(text_body: str) -> str:
    """Return the plain-text lines preceding the first `>`-quoted line."""
    unquoted_lines = []
    for line in text_body.splitlines():
        if line.lstrip().startswith(">"):
            break
        unquoted_lines.append(line)
    return "\n".join(unquoted_lines)


def _normalize(text: str) -> str:
    """Strip HTML tags, unescape entities, and collapse whitespace.

    Makes the substring check tolerant of Mail wrapping each line in its
    own `<div>`/`<br>` and of `&nbsp;`/`&amp;`-style entity encoding, without
    trying to reproduce Mail's exact rendering.
    """
    without_tags = _TAG_RE.sub(" ", text)
    unescaped = html.unescape(without_tags)
    return " ".join(unescaped.split())


def verify_reply_body_outside_quote(
    raw_source: str, reply_body: str
) -> Tuple[bool, str]:
    """Verify `reply_body` was saved outside Mail's quoted-original block.

    Args:
        raw_source: RFC 822 source of the saved draft (from `get_email_source`).
        reply_body: The plain-text reply body that was supposed to be pasted.

    Returns:
        `(verified, detail)`. `verified` is `True` only when normalized
        `reply_body` is found in the region of the saved body that precedes
        Mail's quote container. `detail` explains which of three outcomes
        occurred: found outside (pass), found only inside the quote (the
        bug #71 describes), or not found at all (paste likely failed for
        an unrelated reason -- see the focus-polling comment in
        `compose.py`).
    """
    reply_snippet = _normalize(reply_body)
    if not reply_snippet:
        return False, "Reply body is empty; nothing to verify."

    html_body, text_body = _extract_bodies(raw_source)

    if html_body is not None:
        if reply_snippet in _normalize(_html_before_quote(html_body)):
            return True, "Reply body found outside the quoted original (HTML)."
        if reply_snippet in _normalize(html_body):
            return False, (
                "Reply body found only inside the quoted original (HTML) -- "
                'it landed inside <blockquote type="cite">, not above it.'
            )
        return False, "Reply body not found in the saved draft's HTML body."

    if text_body is not None:
        if reply_body.strip() in _text_before_quote(text_body):
            return True, "Reply body found outside the quoted original (plain text)."
        if reply_body.strip() in text_body:
            return False, (
                "Reply body found only inside the quoted original (plain text) "
                "-- it landed after a '>' quote marker, not above it."
            )
        return False, "Reply body not found in the saved draft's plain-text body."

    return False, "Saved draft has neither an HTML nor a plain-text body to verify."
