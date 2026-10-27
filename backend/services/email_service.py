import base64
import html
import re

import nh3
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Attachment, ClickTracking, Disposition, FileContent, FileName, FileType, From, Mail,
    ReplyTo, To, TrackingSettings,
)
from config import settings
from time_utils import to_display_time

_sg = SendGridAPIClient(api_key=settings.sendgrid_api_key)


def _pdf_attachment(pdf: bytes, filename: str) -> Attachment:
    """Build the PDF attachment. Encoded per message rather than once because
    SendGrid's helper objects aren't safe to share across Mail instances."""
    return Attachment(
        FileContent(base64.b64encode(pdf).decode()),
        FileName(filename),
        FileType("application/pdf"),
        Disposition("attachment"),
    )


def _attach_extras(message: Mail, extras: list[tuple[bytes, str, str]] | None) -> None:
    """Add the producer's own files — set plots, layout diagrams, scout boards.

    Assigning to `message.attachment` appends rather than replaces in the
    SendGrid helper, so this composes with the call sheet PDF above it.
    """
    for data, filename, content_type in extras or []:
        message.attachment = Attachment(
            FileContent(base64.b64encode(data).decode()),
            FileName(filename),
            FileType(content_type),
            Disposition("attachment"),
        )


def _no_click_tracking() -> TrackingSettings:
    """Send crew the real links, not rewritten ones.

    SendGrid's click tracking replaces every href with a redirect through
    ct.sendgrid.net. Two problems on a call sheet. It mangles URLs: a Google
    Maps link is `?api=1&query=ADDRESS`, and the rewrite lost the second
    parameter, so Google got `api=1` and no address at all — the link opened
    nothing. Apple Maps survived only because its address sits in the *first*
    parameter. Confirmed by comparing the same sheet in the app, where the URL
    is correct and works, against the emailed copy, where it doesn't.

    And it makes every link in the message point at an unfamiliar tracking
    domain rather than maps.apple.com or our own site. On a call sheet arriving
    from a sender crew don't know, that reads as phishing — including on the
    confirmation button, which is the one thing we need them to trust and press.

    Built per message: SendGrid's helper objects aren't safe to share across
    Mail instances. Open tracking is deliberately left alone, so delivery
    visibility in the Activity Feed is unchanged.
    """
    settings_obj = TrackingSettings()
    settings_obj.click_tracking = ClickTracking(False, False)
    return settings_obj


def _wrap_document(inner: str) -> str:
    """Wrap the email body in a real document that asks clients not to re-theme it.

    Without this there's no <head> at all, so a dark-mode client is free to
    invert everything — which is why the yellow confirm button rendered brown in
    the Gmail app. Apple Mail and Outlook honor these declarations; the Gmail
    app may still invert regardless, so the sheet is designed to stay legible
    either way rather than relying on this.
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<style>:root {{ color-scheme: light; supported-color-schemes: light; }}</style>
</head>
<body style="margin:0;padding:0;background:#ffffff;">{inner}</body>
</html>"""


def _band(inner: str, background: str, padding: str = "20px 24px", extra: str = "") -> str:
    """A full-width band sitting above the call sheet, matched to its 680px column.

    Padding goes on an INNER div, never on the 680px box itself. Without
    box-sizing:border-box — which Outlook ignores — padding adds to the width, so
    a band with 24px sides renders 728px wide and visibly overhangs the 680px
    sheet beneath it.
    """
    return (
        f'<div style="max-width:680px;margin:0 auto;background:{background};'
        f'font-family:system-ui,-apple-system,Arial,sans-serif;{extra}">'
        f'<div style="padding:{padding};">{inner}</div>'
        "</div>"
    )


# --- plain-text alternative -------------------------------------------------
#
# Every message here used to go out as HTML only. A single-part text/html mail
# carrying a PDF attachment and several links is a well-known spam heuristic,
# and the producer reported roughly a third of call sheets landing in spam (2026-08-31).
# Auth wasn't the problem — SPF, DKIM and DMARC all pass — so this is the next
# real lever, and it costs nothing to send.
#
# The text part is a genuine fallback, not a "view this in HTML" stub: it
# carries the call time, the confirmation URL as a bare link, and a readable
# rendition of the sheet. Some crew read mail in clients that prefer text, and
# they should get the actual information.

_DROP_ELEMENTS = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
_CELL_END = re.compile(r"(?i)</(td|th)\s*>")
_BLOCK_END = re.compile(r"(?i)</(p|div|tr|h[1-6]|li|table|section|header|footer)\s*>|<br\s*/?>")


def _html_to_text(fragment: str) -> str:
    """Flatten an HTML fragment to readable plain text.

    Block ends become newlines and table cells become spaces before the tags are
    stripped, so a call sheet's rows survive as lines instead of collapsing into
    one run-on paragraph. nh3 does the actual stripping rather than a regex,
    because the sheet is model-generated HTML and malformed markup shouldn't be
    able to leak a tag into the text part.
    """
    text = _DROP_ELEMENTS.sub("", fragment)
    text = _CELL_END.sub(" ", text)
    text = _BLOCK_END.sub("\n", text)
    text = html.unescape(nh3.clean(text, tags=set()))

    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        # Collapse runs of blank lines to a single separator.
        if not line and (not out or not out[-1]):
            continue
        out.append(line)
    return "\n".join(out).strip()


def _call_sheet_text(sheet_html: str, project_name: str, recipient: str, role: str = "",
                     call_time: str | None = None, confirmation_url: str | None = None,
                     notice: str | None = None) -> str:
    """The text/plain twin of the call sheet email."""
    lines = [f"CALL SHEET - {project_name}", ""]
    if notice:
        lines += [notice, ""]
    if call_time:
        lines += [f"YOUR CALL TIME: {call_time}"]
        lines += [recipient + (f" - {role}" if role else ""), ""]
    if confirmation_url:
        lines += ["Confirm you received this call sheet:", confirmation_url, ""]
    lines += ["-" * 46, "", _html_to_text(sheet_html)]
    return "\n".join(lines)


def _sender(from_name: str | None) -> From:
    """Build the From field. Address is always our authenticated domain
    (settings.sendgrid_from_email); display name is the producer when known so
    crew recognize who the call sheet is from."""
    display = f"{from_name} via Set Ready" if from_name else "Set Ready"
    return From(settings.sendgrid_from_email, display)


def _fmt_time(t: str | None) -> str | None:
    # Falls back to the raw value so an oddly-stored time still shows something
    # in the call-time banner instead of vanishing from the email.
    return to_display_time(t) or t


def _call_time_for(person: dict) -> str | None:
    """The call time to show this person: their named call if they have one,
    otherwise their clock time. A named call earns the big banner just as much
    as a time does — "Own Call" is the answer to "when am I due?"""
    return person.get("call_time_note") or _fmt_time(person.get("call_time"))


def send_call_sheet_emails(crew: list, html_content: str, base_url: str, project_name: str, update_note: str | None = None, from_name: str | None = None, reply_to: str | None = None, reminder: bool = False, pdf: bytes | None = None, pdf_filename: str = "Call Sheet.pdf", extras: list[tuple[bytes, str, str]] | None = None) -> None:
    """Send the call sheet to each crew member, personalized with their own call
    time and confirmation link.

    `reminder=True` sends the same sheet as a nudge to someone who hasn't
    confirmed — it only changes the subject and adds a banner, so the sheet they
    open is identical to the one they were already sent.

    `pdf`, when given, is attached only for crew flagged `wants_pdf`. Everyone
    still gets the sheet inline: the attachment is a copy to file or print, not
    the delivery mechanism, and the personalized call-time banner only works
    inline anyway.
    """
    if reminder:
        subject = f"Reminder: Call Sheet — {project_name}"
    else:
        subject = f"{'UPDATED: ' if update_note else ''}Call Sheet — {project_name}"
    for member in crew:
        confirmation_url = f"{base_url}/confirm/{member['confirmation_token']}"
        call_time = _call_time_for(member)
        role = member.get("role") or ""
        safe_name = html.escape(member["name"])
        safe_role = html.escape(role)

        update_banner = ""
        if reminder:
            update_banner = _band(
                '<p style="color:#312e81;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin:0 0 3px 0;">Reminder</p>'
                '<p style="color:#312e81;font-size:13px;margin:0;">We haven&rsquo;t heard back from you yet — please confirm you received this call sheet.</p>',
                background="#eef2ff", padding="12px 24px", extra="border-bottom:2px solid #4f46e5;",
            )
        elif update_note:
            update_banner = _band(
                '<p style="color:#92400e;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin:0 0 3px 0;">&#9888; Updated Call Sheet</p>'
                f'<p style="color:#92400e;font-size:13px;margin:0;">{html.escape(update_note)}</p>',
                background="#fef3c7", padding="12px 24px", extra="border-bottom:2px solid #f59e0b;",
            )

        personal_banner = ""
        if call_time:
            personal_banner = _band(
                '<p style="color:rgba(255,255,255,0.65);font-size:11px;text-transform:uppercase;letter-spacing:2px;margin:0 0 6px 0;">Your Call Time</p>'
                f'<p style="color:#ffffff;font-size:38px;font-weight:700;margin:0;letter-spacing:-0.5px;">{call_time}</p>'
                f'<p style="color:rgba(255,255,255,0.55);font-size:12px;margin:8px 0 0 0;">{safe_name}{(" · " + safe_role) if role else ""}</p>',
                background="#1e3359", extra="text-align:center;",
            )

        # Crew were missing this. In navy on white it read as the sheet's own
        # branding — the same color as every section header below it — so it
        # looked like a logo rather than the one thing we need them to press.
        # Yellow appears nowhere else in the sheet, which is the point.
        top_bar = _band(
            f'<a href="{confirmation_url}" style="display:block;background:#facc15;color:#111111;'
            'text-decoration:none;font-size:17px;font-weight:700;line-height:1.3;padding:18px 24px;'
            'border-radius:8px;border:2px solid #111111;letter-spacing:0.02em;">'
            "CLICK TO CONFIRM CALL SHEET</a>"
            '<p style="color:#444444;font-size:14px;font-weight:600;margin:12px 0 0 0;">Tap above to let the producer know you got this.</p>',
            background="#ffffff", padding="22px 24px",
            extra="text-align:center;border-bottom:1px solid #e5e7eb;",
        )

        body = _wrap_document(f"{update_banner}{top_bar}{personal_banner}{html_content}")
        if reminder:
            notice = "REMINDER: we haven't heard back from you yet - please confirm you received this call sheet."
        elif update_note:
            notice = f"UPDATED CALL SHEET: {update_note}"
        else:
            notice = None
        message = Mail(
            from_email=_sender(from_name),
            to_emails=To(member["email"], member["name"]),
            subject=subject,
            plain_text_content=_call_sheet_text(
                html_content, project_name, member["name"], role,
                call_time=call_time, confirmation_url=confirmation_url, notice=notice,
            ),
            html_content=body,
        )
        message.tracking_settings = _no_click_tracking()
        if reply_to:
            message.reply_to = ReplyTo(reply_to, from_name or None)
        if pdf and member.get("wants_pdf"):
            message.attachment = _pdf_attachment(pdf, pdf_filename)
        # Unconditional, unlike the sheet PDF above: wants_pdf is about wanting
        # a copy of the call sheet to file. A set plot is information nobody on
        # the unit can do without.
        _attach_extras(message, extras)
        _sg.send(message)


def send_call_sheet_to_contacts(contacts: list, html_content: str, project_name: str, update_note: str | None = None, from_name: str | None = None, reply_to: str | None = None, pdf: bytes | None = None, pdf_filename: str = "Call Sheet.pdf", extras: list[tuple[bytes, str, str]] | None = None) -> None:
    subject = f"{'UPDATED: ' if update_note else ''}Call Sheet — {project_name}"
    for contact in contacts:
        update_banner = ""
        if update_note:
            update_banner = _band(
                '<p style="color:#92400e;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;margin:0 0 3px 0;">&#9888; Updated Call Sheet</p>'
                f'<p style="color:#92400e;font-size:13px;margin:0;">{html.escape(update_note)}</p>',
                background="#fef3c7", padding="12px 24px", extra="border-bottom:2px solid #f59e0b;",
            )
        message = Mail(
            from_email=_sender(from_name),
            to_emails=To(contact["email"], contact["name"]),
            subject=subject,
            # Contacts get no call time and no confirm link — they're clients and
            # vendors, not unit, so their text part is the sheet and nothing else.
            plain_text_content=_call_sheet_text(
                html_content, project_name, contact["name"],
                notice=f"UPDATED CALL SHEET: {update_note}" if update_note else None,
            ),
            html_content=_wrap_document(f"{update_banner}{html_content}"),
        )
        message.tracking_settings = _no_click_tracking()
        if reply_to:
            message.reply_to = ReplyTo(reply_to, from_name or None)
        if pdf and contact.get("wants_pdf", True):
            message.attachment = _pdf_attachment(pdf, pdf_filename)
        _attach_extras(message, extras)
        _sg.send(message)


def send_support_request(name: str, email: str, message: str) -> None:
    """Email a 'Need help?' submission to the support inbox. From our own
    domain, with Reply-To set to the submitter so a reply reaches them directly."""
    safe_name = html.escape(name)
    safe_email = html.escape(email)
    safe_message = html.escape(message)
    body = f"""
<p style="font-family:sans-serif;font-size:14px;color:#111;"><strong>From:</strong> {safe_name} &lt;{safe_email}&gt;</p>
<hr style="border:none;border-top:1px solid #e5e7eb;margin:12px 0;" />
<p style="font-family:sans-serif;font-size:14px;color:#111;white-space:pre-wrap;">{safe_message}</p>
"""
    message_obj = Mail(
        from_email=From(settings.sendgrid_from_email, "Set Ready Support"),
        to_emails=To(settings.support_email),
        subject=f"Support request from {name}",
        plain_text_content=f"From: {name} <{email}>\n\n{message}",
        html_content=body,
    )
    message_obj.reply_to = ReplyTo(email, name or None)
    _sg.send(message_obj)


def send_waitlist_request(name: str, email: str, note: str | None = None) -> None:
    """Email a private-beta invite request to the support inbox. Reply-To is the
    requester, so replying (with an invite) reaches them directly."""
    safe_name = html.escape(name)
    safe_email = html.escape(email)
    note_block = ""
    if note:
        note_block = (
            '<hr style="border:none;border-top:1px solid #e5e7eb;margin:12px 0;" />'
            f'<p style="font-family:sans-serif;font-size:14px;color:#111;white-space:pre-wrap;">{html.escape(note)}</p>'
        )
    body = f"""
<p style="font-family:sans-serif;font-size:14px;color:#111;"><strong>Invite request from:</strong> {safe_name} &lt;{safe_email}&gt;</p>
{note_block}
"""
    message_obj = Mail(
        from_email=From(settings.sendgrid_from_email, "Set Ready"),
        to_emails=To(settings.support_email),
        subject=f"New invite request from {name}",
        plain_text_content=f"Invite request from: {name} <{email}>" + (f"\n\n{note}" if note else ""),
        html_content=body,
    )
    message_obj.reply_to = ReplyTo(email, name or None)
    _sg.send(message_obj)
