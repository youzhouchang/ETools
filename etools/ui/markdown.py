"""Minimal Markdown → HTML for GitHub release notes (no third-party deps)."""

from __future__ import annotations

import html
import re

_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC = re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])|(?<![\w_])_([^_\n]+)_(?![\w_])")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_UL = re.compile(r"^\s*[-*+]\s+(.*)$")
_OL = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
_HR = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")


def _escape(text: str) -> str:
    return html.escape(text, quote=False)


def _inline(text: str) -> str:
    """Escape then apply common inline Markdown. Code spans keep literal text."""
    parts: list[str] = []
    last = 0
    for m in _INLINE_CODE.finditer(text):
        parts.append(_escape(text[last : m.start()]))
        parts.append(f"<code>{_escape(m.group(1))}</code>")
        last = m.end()
    parts.append(_escape(text[last:]))
    out = "".join(parts)

    def _b(m: re.Match) -> str:
        return f"<strong>{m.group(1) or m.group(2)}</strong>"

    def _i(m: re.Match) -> str:
        return f"<em>{m.group(1) or m.group(2)}</em>"

    def _a(m: re.Match) -> str:
        label, href = m.group(1), m.group(2)
        safe = href.replace('"', "%22").replace("<", "%3C").replace(">", "%3E")
        return f'<a href="{safe}">{label}</a>'

    # Bold/italic only outside <code>…</code> chunks already inserted.
    # Apply on the whole string — code content has no ** or _ after escape.
    out = _BOLD.sub(_b, out)
    out = _ITALIC.sub(_i, out)
    out = _LINK.sub(_a, out)
    return out


def markdown_to_html(md: str) -> str:
    """Convert a GitHub-flavored Markdown subset into simple HTML."""
    if not md or not md.strip():
        return ""

    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    para: list[str] = []
    list_tag: str | None = None

    def flush_para() -> None:
        if para:
            out.append(f"<p>{_inline(' '.join(para).strip())}</p>")
            para.clear()

    def close_list() -> None:
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if _FENCE.match(line):
            flush_para()
            close_list()
            fence = _FENCE.match(line).group(1)
            i += 1
            code_lines: list[str] = []
            while i < n and not lines[i].strip().startswith(fence):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            code = _escape("\n".join(code_lines))
            out.append(f"<pre><code>{code}</code></pre>")
            continue

        if not stripped:
            flush_para()
            close_list()
            i += 1
            continue

        if _HR.match(stripped):
            flush_para()
            close_list()
            out.append("<hr/>")
            i += 1
            continue

        hm = _HEADING.match(stripped)
        if hm:
            flush_para()
            close_list()
            level = min(len(hm.group(1)), 6)
            out.append(f"<h{level}>{_inline(hm.group(2).strip())}</h{level}>")
            i += 1
            continue

        um = _UL.match(line)
        if um:
            flush_para()
            if list_tag != "ul":
                close_list()
                out.append("<ul>")
                list_tag = "ul"
            out.append(f"<li>{_inline(um.group(1).strip())}</li>")
            i += 1
            continue

        om = _OL.match(line)
        if om:
            flush_para()
            if list_tag != "ol":
                close_list()
                out.append("<ol>")
                list_tag = "ol"
            out.append(f"<li>{_inline(om.group(2).strip())}</li>")
            i += 1
            continue

        # Blockquote
        if stripped.startswith(">"):
            flush_para()
            close_list()
            body = stripped.lstrip("> ").strip()
            out.append(f"<blockquote><p>{_inline(body)}</p></blockquote>")
            i += 1
            continue

        # GFM table: header | sep | body rows
        if _TABLE_ROW.match(stripped) and i + 1 < n and _TABLE_SEP.match(lines[i + 1].strip()):
            flush_para()
            close_list()

            def _cells(row: str) -> list[str]:
                inner = row.strip().strip("|")
                return [c.strip() for c in inner.split("|")]

            headers = _cells(stripped)
            i += 2  # skip header + separator
            rows: list[list[str]] = []
            while i < n and _TABLE_ROW.match(lines[i].strip()):
                rows.append(_cells(lines[i].strip()))
                i += 1
            head_html = "".join(f"<th>{_inline(c)}</th>" for c in headers)
            body_rows = []
            for row in rows:
                tds = "".join(
                    f"<td>{_inline(row[j]) if j < len(row) else ''}</td>"
                    for j in range(len(headers))
                )
                body_rows.append(f"<tr>{tds}</tr>")
            out.append(
                "<table><thead><tr>"
                + head_html
                + "</tr></thead><tbody>"
                + "".join(body_rows)
                + "</tbody></table>"
            )
            continue

        close_list()
        para.append(stripped)
        i += 1

    flush_para()
    close_list()
    return "\n".join(out)


def markdown_document(md: str, *, title: str = "", text_color: str = "#1f2933",
                      link_color: str = "#1a73e8", code_bg: str = "#eef1f5") -> str:
    """Wrap converted Markdown in a standalone HTML document for QTextBrowser."""
    body = markdown_to_html(md) or "<p></p>"
    title_html = f"<p style='font-weight:600'>{_escape(title)}</p>" if title else ""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>
body {{ font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
       color: {text_color}; font-size: 13px; line-height: 1.45; }}
h1,h2,h3,h4,h5,h6 {{ font-weight: 600; margin: 0.6em 0 0.3em; }}
h1 {{ font-size: 1.35em; }} h2 {{ font-size: 1.2em; }} h3 {{ font-size: 1.05em; }}
p {{ margin: 0.35em 0; }}
ul, ol {{ margin: 0.3em 0 0.4em 1.2em; padding: 0; }}
li {{ margin: 0.15em 0; }}
code {{ background: {code_bg}; padding: 1px 4px; border-radius: 3px;
       font-family: Consolas, 'Courier New', monospace; font-size: 0.92em; }}
pre {{ background: {code_bg}; padding: 8px 10px; border-radius: 4px;
      white-space: pre-wrap; }}
pre code {{ background: transparent; padding: 0; }}
a {{ color: {link_color}; }}
blockquote {{ border-left: 3px solid {code_bg}; margin: 0.4em 0;
             padding: 0.1em 0 0.1em 0.7em; color: inherit; opacity: 0.9; }}
hr {{ border: none; border-top: 1px solid {code_bg}; margin: 0.6em 0; }}
table {{ border-collapse: collapse; margin: 0.5em 0; width: 100%;
        font-size: 0.95em; table-layout: fixed; }}
th, td {{ border: 1px solid {code_bg}; padding: 4px 8px; text-align: left;
         word-wrap: break-word; overflow-wrap: anywhere; }}
th {{ background: {code_bg}; font-weight: 600; }}
tr:nth-child(even) td {{ opacity: 0.95; }}
</style></head><body>
{title_html}
{body}
</body></html>"""
