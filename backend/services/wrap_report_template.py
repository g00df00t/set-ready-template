"""Render the wrap report. Same Jinja environment as the call sheet, opposite
delivery constraints.

The call sheet is email, so it is inline styles and table layout. This one is
only ever served into a browser, so it can use a <style> block, grid and
percentages — which is what makes the timeline responsive.

⚠️ Every selector in the template is scoped under `.wrap-report`. The HTML is
injected into an app page, so an unscoped rule here would repaint the whole
application. If you add CSS to the template, scope it.

Autoescaping comes from the shared environment and is the same story it is for
the call sheet: producer free text (block descriptions, parking notes) reaches
this page verbatim, and escaping at the insertion point is the reason that's safe.
"""

from services.call_sheet_template import _environment


def render_wrap_report(data: dict) -> str:
    """build_wrap_data() output in, one HTML fragment out."""
    return _environment().get_template("wrap_report.html.j2").render(**data)
