"""Append-only usage logging.

Records the events that cost money — Claude generations and outbound email — so
the operator can answer "is this being used, and by whom" without reading any
customer's content. See supabase/schema.sql for the table and why it holds no PII.

Every write here is best-effort. Metering must never be the reason a producer
can't get their call sheet out the door, so a missing table, a Supabase blip, or
anything else is logged and swallowed. That also means this file is safe to
deploy before the migration is run — a lesson from the account-deletion cascade,
where endpoint logic depended on a migration that hadn't been applied yet.
"""

import logging

logger = logging.getLogger(__name__)

GENERATED = "call_sheet_generated"
SENT = "call_sheet_sent"
REMINDED = "call_sheet_reminded"
#: A wrap report was opened. Costs nothing to serve; recorded because whether
#: producers come back to a finished job is the open question about the feature.
WRAP_VIEWED = "wrap_report_viewed"
#: A public share link was minted. Recorded once per link, not per view — the
#: question is whether producers share these at all, and counting anonymous
#: views would attribute a client's reading to the producer's account.
WRAP_SHARED = "wrap_report_shared"


def record_event(client, user_id, project_id, event_type, recipient_count=None):
    """Log one usage event. Never raises."""
    try:
        client.table("usage_events").insert({
            "user_id": str(user_id),
            "project_id": str(project_id) if project_id else None,
            "event_type": event_type,
            "recipient_count": recipient_count,
        }).execute()
    except Exception as e:
        logger.warning("usage event %s not recorded: %s", event_type, e)


# ── AI imports ───────────────────────────────────────────────────────────────
#
# Every paste-a-list or call-sheet import is one model call, and unlike the call
# sheet itself (a template since September — no model) it genuinely costs
# money. So each records what the model reported spending: token counts and the
# model id. Never the text, the file name, or anyone's name — the columns hold
# numbers and a model string, nothing a producer typed.
#
# Needs supabase/usage_import_events.sql. Until that runs, the insert is refused
# by the event_type constraint (and the missing columns), the warning below is
# logged, and the import carries on exactly as before.

IMPORT_ROSTER_PASTE = "import_roster_paste"
IMPORT_ROSTER_CALL_SHEET = "import_roster_call_sheet"
IMPORT_CREW_PASTE = "import_crew_paste"
IMPORT_TALENT_PASTE = "import_talent_paste"
IMPORT_CONTACTS_PASTE = "import_contacts_paste"
IMPORT_RECEIPT = "import_receipt"            # needs supabase/receipts.sql too
IMPORT_ESTIMATE = "import_estimate"          # needs supabase/estimate.sql too

IMPORT_EVENTS = (IMPORT_ROSTER_PASTE, IMPORT_ROSTER_CALL_SHEET,
                 IMPORT_CREW_PASTE, IMPORT_TALENT_PASTE, IMPORT_CONTACTS_PASTE, IMPORT_RECEIPT,
                 IMPORT_ESTIMATE)


def record_import(client, user_id, project_id, event_type, model, input_tokens, output_tokens):
    """Log one AI import's measured spend. Never raises."""
    try:
        client.table("usage_events").insert({
            "user_id": str(user_id),
            "project_id": str(project_id) if project_id else None,
            "event_type": event_type,
            "model": str(model) if model else None,
            "input_tokens": int(input_tokens) if input_tokens is not None else None,
            "output_tokens": int(output_tokens) if output_tokens is not None else None,
        }).execute()
    except Exception as e:
        # The type only: a Postgres refusal quotes the failing row. That row is
        # counts and ids today, but a log line needn't depend on it staying so.
        logger.warning("usage event %s not recorded: %s", event_type, type(e).__name__)


def import_recorder(client, user_id, project_id, event_type):
    """A callback for claude_service's parsers. It is called with the model and
    token counts the moment the model answers — before the reply is parsed — so
    a reply that fails to parse is still recorded as the spend it was."""
    def on_usage(model, input_tokens, output_tokens):
        record_import(client, user_id, project_id, event_type, model, input_tokens, output_tokens)
    return on_usage
