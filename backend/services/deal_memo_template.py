"""Render a deal memo from deal_memo_data.py's output. No model involved.

Same shape as call_sheet_template.py: a template does the layout, this module
does the branching that needs testing without parsing HTML (here, just which
signature block renders). Output goes to WeasyPrint only — never emailed,
never shown on a public page — so unlike the call sheet it's free to use a
<style> block instead of inline styles.

The fixed boilerplate in deal_memo.html.j2 (sections 3-11: work expectations,
responsibilities, payroll/insurance structure, cancellation terms, etc.) is
transcribed from a working producer's own real templates, confirmed against both her
agency and non-agency variants — see docs/master-record-documents-review.md
§2. It reflects one producer's actual standing terms with her own payroll
provider and insurance arrangement, not a general legal template — the only
parts that vary by job are client/production-company/payroll-provider names,
which are interpolated from the project. A producer with a different payroll
or insurance setup would need their own boilerplate; nothing here tries to
generalize that.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

_TEMPLATE_DIR = Path(__file__).parent / "templates"

_env: Environment | None = None


def _environment() -> Environment:
    global _env
    if _env is None:
        _env = Environment(
            loader=FileSystemLoader(_TEMPLATE_DIR),
            autoescape=select_autoescape(["html", "j2", "html.j2"], default=True),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        _env.filters["nl2br"] = nl2br
    return _env


def nl2br(value) -> Markup:
    """Same rule as the call sheet's filter: escape first, then substitute
    line breaks, then mark safe — never the other order. Producer free text
    (here, the per-person Dates block) keeps its line breaks and nothing else
    gets a pass through autoescaping."""
    return Markup(str(escape(value or "")).replace("\n", "<br>"))


def render_deal_memo(data: dict) -> str:
    """deal_memo_data.py's output in, one PDF-ready HTML document out."""
    return _environment().get_template("deal_memo.html.j2").render(**data)
