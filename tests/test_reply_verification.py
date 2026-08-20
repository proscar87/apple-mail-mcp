"""Tests for verify_reply_body_outside_quote (#71)."""

import unittest

from apple_mail_mcp.tools.reply_verification import verify_reply_body_outside_quote

_HEADERS = (
    "From: sender@example.com\r\n"
    "To: reply@example.com\r\n"
    "Subject: Re: Weekly sync\r\n"
    "MIME-Version: 1.0\r\n"
)

_ORIGINAL_HTML = (
    '<blockquote type="cite">'
    "<div>On Jan 1, 2026, sender wrote:</div>"
    "<div>Can we move the meeting?</div>"
    "</blockquote>"
)


def _multipart_source(new_body_html: str, new_body_text: str) -> str:
    """Build a multipart/alternative RFC 822 source, matching what Mail
    actually produces for an HTML reply (text/plain fallback + text/html)."""
    boundary = "----MailBoundary"
    return (
        _HEADERS
        + f'Content-Type: multipart/alternative; boundary="{boundary}"\r\n'
        + "\r\n"
        + f"--{boundary}\r\n"
        + "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        + new_body_text
        + "\r\n"
        + f"--{boundary}\r\n"
        + "Content-Type: text/html; charset=utf-8\r\n\r\n"
        + new_body_html
        + f"\r\n--{boundary}--\r\n"
    )


class VerifyReplyBodyOutsideQuoteTests(unittest.TestCase):
    def test_body_correctly_placed_above_the_quote_verifies(self):
        """The intended case: new content above the blockquote."""
        source = _multipart_source(
            new_body_html=f"<div>Yes, 3pm works.</div>{_ORIGINAL_HTML}",
            new_body_text="Yes, 3pm works.\n\nOn Jan 1, 2026, sender wrote:\n> Can we move the meeting?",
        )

        verified, detail = verify_reply_body_outside_quote(
            source, "Yes, 3pm works."
        )

        self.assertTrue(verified, detail)
        self.assertIn("outside", detail)

    def test_body_landed_inside_the_quote_is_caught(self):
        """The #71 bug: the paste ends up inside the blockquote, not above it.

        Before this module existed, `reply_to_email` reported success from
        text presence alone, which this case would have wrongly passed.
        """
        html_body = (
            '<blockquote type="cite">'
            "<div>Yes, 3pm works.</div>"
            "<div>On Jan 1, 2026, sender wrote:</div>"
            "<div>Can we move the meeting?</div>"
            "</blockquote>"
        )
        source = _multipart_source(
            new_body_html=html_body,
            new_body_text="> Yes, 3pm works.\n> On Jan 1, 2026, sender wrote:\n> Can we move the meeting?",
        )

        verified, detail = verify_reply_body_outside_quote(
            source, "Yes, 3pm works."
        )

        self.assertFalse(verified)
        self.assertIn("only inside the quoted original", detail)

    def test_body_missing_entirely_is_distinguished_from_quoted(self):
        """A failed paste (empty reply) must not be reported as 'inside the
        quote' -- that's a different, more specific failure than 'not
        found at all', and callers should be able to tell them apart."""
        source = _multipart_source(
            new_body_html=_ORIGINAL_HTML,
            new_body_text="On Jan 1, 2026, sender wrote:\n> Can we move the meeting?",
        )

        verified, detail = verify_reply_body_outside_quote(
            source, "Yes, 3pm works."
        )

        self.assertFalse(verified)
        self.assertIn("not found", detail)
        self.assertNotIn("only inside", detail)

    def test_reply_with_no_quote_block_at_all_still_verifies(self):
        """A reply to a message with no prior thread (or a compose, not a
        reply) has no blockquote to be inside of -- presence anywhere in
        the body is correctly sufficient."""
        source = _multipart_source(
            new_body_html="<div>Sounds good.</div>",
            new_body_text="Sounds good.",
        )

        verified, detail = verify_reply_body_outside_quote(source, "Sounds good.")

        self.assertTrue(verified, detail)

    def test_plain_text_only_message_uses_the_gt_marker_path(self):
        """No HTML part at all: falls back to '>'-line quote detection."""
        source = (
            _HEADERS
            + "Content-Type: text/plain; charset=utf-8\r\n\r\n"
            + "Yes, 3pm works.\n\n> Can we move the meeting?\n"
        )

        verified, detail = verify_reply_body_outside_quote(
            source, "Yes, 3pm works."
        )

        self.assertTrue(verified, detail)

    def test_plain_text_only_message_catches_body_inside_quote(self):
        source = (
            _HEADERS
            + "Content-Type: text/plain; charset=utf-8\r\n\r\n"
            + "> Yes, 3pm works.\n> Can we move the meeting?\n"
        )

        verified, detail = verify_reply_body_outside_quote(
            source, "Yes, 3pm works."
        )

        self.assertFalse(verified)
        self.assertIn("only inside the quoted original", detail)

    def test_html_wrapped_across_multiple_divs_still_matches(self):
        """Mail wraps each line in its own <div>; the tag-stripping
        normalization must not require an exact-string match against the
        raw HTML."""
        source = _multipart_source(
            new_body_html="<div>Yes,</div><div>3pm&nbsp;works.</div>" + _ORIGINAL_HTML,
            new_body_text="Yes,\n3pm works.",
        )

        verified, _ = verify_reply_body_outside_quote(source, "Yes, 3pm works.")

        self.assertTrue(verified)

    def test_empty_reply_body_does_not_verify(self):
        source = _multipart_source(
            new_body_html=_ORIGINAL_HTML, new_body_text="quoted only"
        )

        verified, detail = verify_reply_body_outside_quote(source, "   ")

        self.assertFalse(verified)
        self.assertIn("empty", detail)

    def test_message_with_neither_html_nor_text_body_reports_that_plainly(self):
        source = (
            _HEADERS
            + "Content-Type: application/octet-stream\r\n\r\n"
            + "binary-ish-payload"
        )

        verified, detail = verify_reply_body_outside_quote(source, "Yes, 3pm works.")

        self.assertFalse(verified)
        self.assertIn("neither", detail)


if __name__ == "__main__":
    unittest.main()
