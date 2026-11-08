"""
Advance Quiz Bot — Open Source Project
Customized for Akhil Quiz & Runner Bot.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Literal, Optional

logger = logging.getLogger(__name__)

PdfStyle = Literal["classic", "modern"]

_SECTION_COLORS = [
    "#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7",
    "#DDA0DD", "#98D8C8", "#F7DC6F", "#BB8FCE", "#85C1E9",
]


def _render_math_in_html(text: str) -> str:
    """Convert $$...$$ (display) and $...$ (inline) LaTeX to MathML so
    WeasyPrint renders proper math symbols. Falls back to raw text if
    latex2mathml isn't installed or conversion fails."""
    try:
        import latex2mathml.converter as _lc
    except ImportError:
        return text

    def _display(m: re.Match) -> str:
        try:
            ml = _lc.convert(m.group(1).strip())
            return ml.replace("<math>", '<math display="block">', 1)
        except Exception:
            return m.group(0)

    def _inline(m: re.Match) -> str:
        try:
            return _lc.convert(m.group(1).strip())
        except Exception:
            return m.group(0)

    text = re.sub(r"\$\$([\s\S]+?)\$\$", _display, text)
    text = re.sub(r"(?<!\$)\$(?!\$)([^$\n]+?)(?<!\$)\$(?!\$)", _inline, text)
    return text


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def _safe_html(text: str, render_math: bool = True) -> str:
    """HTML-escape text for embedding in the PDF template, converting
    LaTeX to MathML first (if present) so the MathML tags survive escaping."""
    if render_math and ("$$" in text or "$" in text):
        rendered = _render_math_in_html(text)
        parts = re.split(r"(<math[\s\S]*?</math>)", rendered)
        escaped = []
        for part in parts:
            if part.startswith("<math"):
                escaped.append(part)
            else:
                escaped.append(
                    part.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
                )
        return "".join(escaped)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")


def render_markdown_to_html(text: str) -> str:
    """Convert a GitHub-flavored-markdown subset (tables, lists, blockquotes,
    inline code/code blocks, bold/italic/strikethrough, headings, math,
    horizontal rules, links/images, task lists) into HTML for PDF embedding."""
    if not text:
        return ""

    code_blocks: dict[str, str] = {}
    code_counter = 0

    def _save_code_block(match: re.Match) -> str:
        nonlocal code_counter
        code_counter += 1
        placeholder = f"__CODE_BLOCK_{code_counter}__"
        code_blocks[placeholder] = match.group(0)
        return placeholder

    text = re.sub(r"```([\s\S]*?)```", _save_code_block, text)

    inline_codes: dict[str, str] = {}
    inline_counter = 0

    def _save_inline_code(match: re.Match) -> str:
        nonlocal inline_counter
        inline_counter += 1
        placeholder = f"__INLINE_CODE_{inline_counter}__"
        inline_codes[placeholder] = match.group(0)
        return placeholder

    text = re.sub(r"`([^`]+)`", _save_inline_code, text)

    lines = text.split("\n")
    html_lines: list[str] = []
    in_table = False
    table_header = False
    table_rows: list[list[str]] = []
    in_list = False
    list_type: Optional[str] = None
    in_blockquote = False
    blockquote_lines: list[str] = []
    in_code_block = False
    code_block_lang = ""
    code_block_content: list[str] = []
    in_paragraph = False
    paragraph_lines: list[str] = []

    def _flush_paragraph() -> None:
        nonlocal in_paragraph, paragraph_lines
        if in_paragraph and paragraph_lines:
            html_lines.append(f"<p>{' '.join(paragraph_lines)}</p>")
            paragraph_lines = []
            in_paragraph = False

    def _flush_blockquote() -> None:
        nonlocal in_blockquote, blockquote_lines
        if in_blockquote and blockquote_lines:
            html_lines.append(f"<blockquote>{' '.join(blockquote_lines)}</blockquote>")
            blockquote_lines = []
            in_blockquote = False

    def _flush_list() -> None:
        nonlocal in_list, list_type
        if in_list:
            html_lines.append(f"</{list_type}>")
            in_list = False
            list_type = None

    def _process_inline_markdown(line: str) -> str:
        line = line.strip()
        line = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", line)
        line = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", line)
        line = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", line)
        line = re.sub(r"_([^_]+)_", r"<em>\1</em>", line)
        line = re.sub(r"~~([^~]+)~~", r"<del>\1</del>", line)
        for placeholder, code in inline_codes.items():
            if placeholder in line:
                code_content = code[1:-1]
                line = line.replace(placeholder, f"<code>{_escape_html(code_content)}</code>")
        line = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" target="_blank">\1</a>', line)
        line = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r'<img src="\2" alt="\1" style="max-width:100%;"/>', line)
        line = re.sub(
            r"\$\$([\s\S]+?)\$\$",
            lambda m: f'<div class="math-display">\\[ {_escape_html(m.group(1))} \\]</div>',
            line,
        )
        line = re.sub(
            r"(?<!\$)\$(?!\$)([^$\n]+?)(?<!\$)\$(?!\$)",
            lambda m: f'<span class="math-inline">\\( {_escape_html(m.group(1))} \\)</span>',
            line,
        )
        return line

    i = 0
    while i < len(lines):
        line = lines[i]

        if line.strip().startswith("```"):
            if not in_code_block:
                in_code_block = True
                code_block_lang = line.strip()[3:].strip()
                code_block_content = []
                i += 1
                continue
            in_code_block = False
            _flush_paragraph()
            _flush_blockquote()
            _flush_list()
            code_html = _escape_html("\n".join(code_block_content))
            lang_class = f' class="language-{_escape_html(code_block_lang)}"' if code_block_lang else ""
            html_lines.append(f"<pre><code{lang_class}>{code_html}</code></pre>")
            i += 1
            continue

        if in_code_block:
            code_block_content.append(line)
            i += 1
            continue

        if re.match(r"^---+$", line.strip()):
            _flush_paragraph()
            _flush_blockquote()
            _flush_list()
            html_lines.append("<hr/>")
            i += 1
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
        if heading_match:
            _flush_paragraph()
            _flush_blockquote()
            _flush_list()
            level = len(heading_match.group(1))
            content = _process_inline_markdown(heading_match.group(2))
            html_lines.append(f"<h{level}>{content}</h{level}>")
            i += 1
            continue

        if line.strip().startswith(">"):
            if not in_blockquote:
                _flush_paragraph()
                _flush_list()
                in_blockquote = True
            content = line.strip()[1:].strip()
            blockquote_lines.append(_process_inline_markdown(content) if content else "")
            i += 1
            continue
        if in_blockquote:
            _flush_blockquote()

        if "|" in line and not line.strip().startswith("<!--"):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if all(re.match(r"^[\s\-:]+$", c) for c in cells if c):
                table_header = True
                i += 1
                continue
            if cells:
                if not in_table:
                    _flush_paragraph()
                    _flush_blockquote()
                    _flush_list()
                    in_table = True
                    table_header = False
                    table_rows = []
                row_cells = [_process_inline_markdown(cell) if cell else "" for cell in cells]
                table_rows.append(row_cells)
                i += 1
                continue

        ul_match = re.match(r"^(\s*)[*\-+]\s+(.*)$", line)
        ol_match = re.match(r"^(\s*)(\d+)\.\s+(.*)$", line)
        task_match = re.match(r"^(\s*)- \[([ xX])\] (.*)$", line)

        if task_match:
            _flush_paragraph()
            checked = task_match.group(2).lower() == "x"
            content = _process_inline_markdown(task_match.group(3))
            if not in_list or list_type != "ul":
                _flush_list()
                html_lines.append("<ul>")
                in_list, list_type = True, "ul"
            checkbox = "\u2611\ufe0f" if checked else "\u2610"
            html_lines.append(f'<li><span class="task-checkbox">{checkbox}</span> {content}</li>')
            i += 1
            continue

        if ul_match:
            _flush_paragraph()
            content = _process_inline_markdown(ul_match.group(2))
            if not in_list or list_type != "ul":
                _flush_list()
                html_lines.append("<ul>")
                in_list, list_type = True, "ul"
            html_lines.append(f"<li>{content}</li>")
            i += 1
            continue

        if ol_match:
            _flush_paragraph()
            content = _process_inline_markdown(ol_match.group(3))
            if not in_list or list_type != "ol":
                _flush_list()
                html_lines.append("<ol>")
                in_list, list_type = True, "ol"
            html_lines.append(f"<li>{content}</li>")
            i += 1
            continue

        if not line.strip():
            _flush_paragraph()
            _flush_blockquote()
            _flush_list()
            i += 1
            continue

        if not in_paragraph:
            in_paragraph = True
            paragraph_lines = []
        paragraph_lines.append(_process_inline_markdown(line))
        i += 1

    _flush_paragraph()
    _flush_blockquote()
    _flush_list()

    if in_table and table_rows:
        html_lines.append('<table class="md-table">')
        html_lines.append("<thead><tr>")
        for cell in table_rows[0]:
            html_lines.append(f"<th>{cell}</th>")
        html_lines.append("</tr></thead>")
        table_rows = table_rows[1:]
        if table_rows:
            html_lines.append("<tbody>")
            for row in table_rows:
                html_lines.append("<tr>")
                for cell in row:
                    html_lines.append(f"<td>{cell}</td>")
                html_lines.append("</tr>")
            html_lines.append("</tbody>")
        html_lines.append("</table>")

    result = "\n".join(html_lines)
    for placeholder, code_block in code_blocks.items():
        if placeholder in result:
            code_content = code_block[3:-3].strip()
            lines_split = code_content.split("\n")
            lang = ""
            if lines_split and lines_split[0].strip() and not lines_split[0].strip().startswith("```"):
                lang = lines_split[0].strip()
                code_content = "\n".join(lines_split[1:])
            lang_class = f' class="language-{_escape_html(lang)}"' if lang else ""
            result = result.replace(placeholder, f"<pre><code{lang_class}>{_escape_html(code_content)}</code></pre>")
    return result


def _build_section_map(sections: Optional[list[dict]]) -> dict[int, str]:
    section_map: dict[int, str] = {}
    if not sections:
        return section_map
    for sec in sections:
        sec_name = sec.get("name", "")
        q_indices = sec.get("question_indices", [])
        if not q_indices and "start" in sec and "end" in sec:
            q_indices = list(range(sec["start"], sec["end"] + 1))
        for qi in q_indices:
            section_map[int(qi)] = sec_name
    return section_map


def _build_leaderboard_rows(leaderboard: list[dict], style: PdfStyle) -> str:
    rows_html = ""
    for rank, u in enumerate(leaderboard, 1):
        attempted = u["correct"] + u["wrong"]
        acc = (u["correct"] / attempted * 100) if attempted else 0
        minutes, seconds = divmod(u["total_time"], 60)
        medal = {1: "\U0001F947", 2: "\U0001F948", 3: "\U0001F949"}.get(rank, f"{rank}.")
        row_class = "even-row" if rank % 2 == 0 else "odd-row"
        if style == "modern":
            score_color = "#34d399" if u["score"] >= 0 else "#f87171"
            rows_html += (
                f'<tr class="{row_class}">'
                f'<td class="rank-col">{medal}</td>'
                f'<td class="name-col">{_escape_html(str(u["name"])[:35])}</td>'
                f'<td><span class="badge-correct">{u["correct"]}</span></td>'
                f'<td><span class="badge-wrong">{u["wrong"]}</span></td>'
                f'<td class="score-col" style="color:{score_color}; font-weight:700; font-size:11pt;">{u["score"]:.1f}</td>'
                f'<td><span class="badge-acc">{acc:.0f}%</span></td>'
                f"<td>{int(minutes)}m {int(seconds)}s</td></tr>"
            )
        else:
            score_color = "#10b981" if u["score"] >= 0 else "#ef4444"
            rows_html += (
                f'<tr class="{row_class}">'
                f'<td class="rank-col">{medal}</td>'
                f'<td class="name-col">{_escape_html(str(u["name"])[:35])}</td>'
                f'<td>{u["correct"]}</td><td>{u["wrong"]}</td>'
                f'<td class="score-col" style="color:{score_color}; font-weight:bold;">{u["score"]:.1f}</td>'
                f"<td>{acc:.0f}%</td><td>{int(minutes)}m {int(seconds)}s</td></tr>"
            )
    return rows_html


def _build_questions_html(
    questions: list[dict], session_polls: dict, sections: Optional[list[dict]],
    shuffle_options: bool, style: PdfStyle,
) -> str:
    import random

    section_map = _build_section_map(sections)
    questions_html = ""
    polls_list = sorted(session_polls.items(), key=lambda x: x[1].get("question_index", 0))
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    last_section = None

    for i, (_poll_id, pdata) in enumerate(polls_list):
        q_idx = pdata.get("question_index", i)
        if q_idx < 0 or q_idx >= len(questions):
            continue
        q = questions[q_idx]

        sec_name = section_map.get(q_idx, "")
        if sec_name and sec_name != last_section:
            last_section = sec_name
            if style == "modern":
                color = _SECTION_COLORS[len(section_map) % len(_SECTION_COLORS)]
                questions_html += (
                    f'</div><div class="section-banner" '
                    f'style="background: linear-gradient(135deg, {color}, {color}dd);">'
                    f"\U0001F4C2 {_escape_html(sec_name)}</div><div class=\"questions-container\">"
                )
            else:
                safe_sec = sec_name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                questions_html += (
                    f'</div><div class="section-banner">\U0001F4C2 {safe_sec}</div>'
                    f'<div class="questions-container">'
                )

        orig_options = list(q.get("options", []))
        orig_correct_id = q.get("correct_option_id", 0)
        orig_correct_ids = orig_correct_id if isinstance(orig_correct_id, list) else [orig_correct_id]
        try:
            orig_correct_ids = [int(c) for c in orig_correct_ids]
        except Exception:
            orig_correct_ids = [0]

        if shuffle_options:
            idx_list = list(range(len(orig_options)))
            random.shuffle(idx_list)
            shuffled_options = [orig_options[k] for k in idx_list]
            old_to_new = {old: new for new, old in enumerate(idx_list)}
            correct_ids_final = [old_to_new[c] for c in orig_correct_ids if c in old_to_new]
        else:
            shuffled_options = orig_options
            correct_ids_final = orig_correct_ids

        opts_html = ""
        for j, opt in enumerate(shuffled_options):
            is_correct = j in correct_ids_final
            cls = "opt-correct" if is_correct else "opt-normal"
            opts_html += f'<div class="{cls}"><span class="opt-letter">{letters[j]})</span> {_safe_html(str(opt))}</div>'

        expl_raw = q.get("explanation", "")
        expl_html = (
            f'<div class="explanation-box"><strong>\U0001F4A1 Explanation:</strong> {_safe_html(str(expl_raw))}</div>'
            if expl_raw else ""
        )
        reply_raw = q.get("reply_text", "")
        reply_html = (
            f'<div class="reference-box"><strong>\U0001F4DD Reference:</strong> {_safe_html(str(reply_raw))}</div>'
            if reply_raw else ""
        )
        safe_q = _safe_html(str(q.get("question", "")))

        questions_html += (
            f'<div class="question-card"><div class="q-header">'
            f'<span class="q-badge">Q{i + 1}</span><span class="q-text">{safe_q}</span></div>'
            f'<div class="options-container">{opts_html}</div>{reply_html}{expl_html}</div>'
        )

    return questions_html


_CLASSIC_CSS = """
@page { size: A4; margin: 1.5cm 1.5cm 2cm 1.5cm;
  @bottom-center { content: "Page " counter(page); font-family: 'Noto Sans', sans-serif; font-size: 9pt; color: #9ca3af; }
  @top-right { content: "{title_short}"; font-family: 'Noto Sans', sans-serif; font-size: 8pt; color: #9ca3af; font-style: italic; } }
body { font-family: 'Noto Sans', 'Noto Sans Devanagari', sans-serif; color: #f3f4f6; line-height: 1.5; font-size: 10pt; background-color: #111827; }
.report-header { text-align: center; border-bottom: 2px solid #374151; padding-bottom: 15px; margin-bottom: 20px; }
.brand-sub { font-size: 9pt; color: #60a5fa; margin-bottom: 6px; font-weight: 600; }
.brand-sub a { color: #60a5fa; text-decoration: none; }
.brand-links { margin-top: 8px; font-size: 8.5pt; color: #9ca3af; }
.brand-links a { color: #38bdf8; text-decoration: none; margin: 0 6px; font-weight: 600; }
.report-title { font-family: 'Merriweather', serif; font-size: 20pt; color: #f9fafb; margin: 0 0 5px 0; }
.report-meta { font-size: 9pt; color: #9ca3af; margin-top: 5px; }
.report-meta span { margin: 0 8px; }
.section-title { background-color: #1f2937; color: #f9fafb; padding: 6px 10px; font-weight: bold; font-size: 11pt; margin-top: 20px; margin-bottom: 10px; border-radius: 4px; text-transform: uppercase; letter-spacing: 1px; page-break-after: avoid; }
table.leaderboard { width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 8.5pt; box-shadow: 0 1px 3px rgba(0,0,0,0.5); }
table.leaderboard th { background-color: #374151; color: #f9fafb; padding: 6px; text-align: center; font-weight: 600; }
table.leaderboard td { padding: 6px; text-align: center; border-bottom: 1px solid #4b5563; }
.rank-col { width: 35px; font-weight: bold; }
.name-col { text-align: left !important; max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.even-row { background-color: #1f2937; } .odd-row { background-color: #111827; }
.questions-container { column-count: 2; column-gap: 20px; column-rule: 1px solid #4b5563; }
.question-card { border: 1px solid #374151; border-left: 3px solid #6b7280; border-radius: 4px; padding: 8px; margin-bottom: 12px; page-break-inside: avoid; break-inside: avoid; background-color: #1f2937; }
.q-header { display: flex; align-items: baseline; margin-bottom: 6px; }
.q-badge { background-color: #4b5563; color: #f9fafb; font-weight: bold; padding: 1px 6px; border-radius: 3px; font-size: 8pt; margin-right: 8px; min-width: 25px; text-align: center; flex-shrink: 0; }
.q-text { font-weight: 600; color: #f3f4f6; font-size: 9.5pt; line-height: 1.4; }
.options-container { margin-left: 2px; }
.opt-normal { color: #d1d5db; margin-bottom: 2px; padding: 1px 0; font-size: 9pt; }
.opt-correct { color: #10b981; font-weight: 600; margin-bottom: 2px; padding: 1px 4px; background-color: rgba(16, 185, 129, 0.1); border-radius: 3px; font-size: 9pt; }
.opt-letter { font-weight: bold; margin-right: 4px; color: #9ca3af; }
.explanation-box { margin-top: 6px; padding: 5px; background-color: rgba(245, 158, 11, 0.1); border-left: 2px solid #f59e0b; font-size: 8pt; color: #fcd34d; border-radius: 0 3px 3px 0; line-height: 1.3; }
math { font-size: 9.5pt; } math[display="block"] { display: block; margin: 6px auto; text-align: center; }
.reference-box { margin-top: 6px; padding: 5px; background-color: rgba(59, 130, 246, 0.1); border-left: 2px solid #3b82f6; font-size: 8pt; color: #93c5fd; border-radius: 0 3px 3px 0; line-height: 1.3; }
.footer-info { text-align: center; font-size: 7.5pt; color: #9ca3af; margin-top: 20px; border-top: 1px solid #4b5563; padding-top: 8px; }
.footer-info a { color: #60a5fa; text-decoration: none; font-weight: bold; }
.section-banner { column-span: all; background: linear-gradient(90deg, #374151, #4b5563); color: #f9fafb; padding: 7px 12px; font-weight: bold; font-size: 10.5pt; margin: 16px 0 10px 0; border-radius: 5px; letter-spacing: 0.5px; page-break-after: avoid; }
"""

_MODERN_CSS = """
@page { size: A4; margin: 1.5cm 1.5cm 2cm 1.5cm;
  @bottom-center { content: "Page " counter(page); font-family: 'Noto Sans', sans-serif; font-size: 9pt; color: #9ca3af; } }
body { font-family: 'Noto Sans', 'Noto Sans Devanagari', sans-serif; color: #f3f4f6; line-height: 1.6; font-size: 10pt; background-color: #111827; }
.report-header { text-align: center; padding: 22px; margin-bottom: 20px; background: linear-gradient(135deg, #1f2937, #374151); border-radius: 10px; color: #f9fafb; border: 1px solid #4b5563; }
.brand-sub { font-size: 9.5pt; color: #93c5fd; margin-bottom: 6px; font-weight: 700; letter-spacing: 0.5px; }
.brand-sub a { color: #93c5fd; text-decoration: none; }
.brand-links { margin-top: 10px; font-size: 8.5pt; color: #d1d5db; }
.brand-links a { color: #38bdf8; text-decoration: none; margin: 0 8px; font-weight: bold; background: rgba(56, 189, 248, 0.1); padding: 3px 8px; border-radius: 4px; }
.report-title { font-family: 'Merriweather', serif; font-size: 22pt; margin: 0 0 8px 0; color: #f9fafb; }
.report-meta { font-size: 9.5pt; opacity: 0.9; color: #d1d5db; margin-top: 8px; }
.report-meta span { margin: 0 8px; }
.section-title { background: linear-gradient(135deg, #1f2937, #374151); color: #f9fafb; padding: 8px 12px; font-weight: bold; font-size: 12pt; margin-top: 22px; margin-bottom: 12px; border-radius: 6px; page-break-after: avoid; border: 1px solid #4b5563; }
table.leaderboard { width: 100%; border-collapse: collapse; margin-bottom: 22px; font-size: 8.5pt; box-shadow: 0 2px 4px rgba(0,0,0,0.5); }
table.leaderboard th { background: #374151; color: #f9fafb; padding: 7px; text-align: center; font-weight: 600; border-bottom: 2px solid #4b5563; }
table.leaderboard td { padding: 7px; text-align: center; border-bottom: 1px solid #4b5563; }
.rank-col { width: 35px; font-weight: bold; }
.name-col { text-align: left !important; max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.even-row { background-color: #1f2937; } .odd-row { background-color: #111827; }
.badge-correct { color: #34d399; font-weight: 700; } .badge-wrong { color: #f87171; font-weight: 700; } .badge-acc { color: #818cf8; font-weight: 700; }
.questions-container { column-count: 2; column-gap: 22px; column-rule: 1px solid #4b5563; }
.question-card { border: 1px solid #374151; border-left: 4px solid #6b7280; border-radius: 6px; padding: 9px; margin-bottom: 14px; page-break-inside: avoid; break-inside: avoid; background: #1f2937; }
.q-header { display: flex; align-items: baseline; margin-bottom: 7px; }
.q-badge { background: linear-gradient(135deg, #374151, #4b5563); color: #f9fafb; font-weight: bold; padding: 2px 7px; border-radius: 4px; font-size: 8pt; margin-right: 8px; min-width: 25px; text-align: center; flex-shrink: 0; }
.q-text { font-weight: 700; color: #f9fafb; font-size: 9.5pt; line-height: 1.45; }
.options-container { margin-left: 2px; }
.opt-normal { color: #d1d5db; margin-bottom: 3px; padding: 1px 0; font-size: 9pt; }
.opt-correct { color: #34d399; font-weight: 700; margin-bottom: 3px; padding: 2px 5px; background: rgba(16, 185, 129, 0.1); border-radius: 4px; font-size: 9pt; }
.opt-letter { font-weight: bold; margin-right: 4px; color: #9ca3af; }
.explanation-box { margin-top: 7px; padding: 6px; background: rgba(245, 158, 11, 0.1); border-left: 3px solid #f59e0b; font-size: 8pt; color: #fcd34d; border-radius: 0 4px 4px 0; line-height: 1.35; }
math { font-size: 9.5pt; } math[display="block"] { display: block; margin: 6px auto; text-align: center; }
.reference-box { margin-top: 7px; padding: 6px; background: rgba(139, 92, 246, 0.1); border-left: 3px solid #8b5cf6; font-size: 8pt; color: #c4b5fd; border-radius: 0 4px 4px 0; line-height: 1.35; }
.footer-info { text-align: center; font-size: 7.5pt; color: #9ca3af; margin-top: 22px; border-top: 1px solid #4b5563; padding-top: 8px; }
.footer-info a { color: #60a5fa; text-decoration: none; font-weight: bold; }
.section-banner { column-span: all; color: #f9fafb; padding: 8px 14px; font-weight: bold; font-size: 10.5pt; margin: 18px 0 10px 0; border-radius: 6px; letter-spacing: 0.5px; page-break-after: avoid; }
"""


def render_quiz_pdf(
    quiz_name: str,
    chat_title: str,
    questions: list[dict],
    leaderboard: list[dict],
    session_polls: dict,
    neg: float,
    correct_mark: float,
    output_path: str,
    sections: Optional[list[dict]] = None,
    bg_image_b64: Optional[str] = None,
    shuffle_options: bool = False,
    style: PdfStyle = "classic",
) -> bool:
    """Render a professional quiz PDF report (questions, answers, and
    leaderboard) via WeasyPrint. Synchronous -- callers MUST run this via
    `loop.run_in_executor`. Returns True on success, False if WeasyPrint
    isn't installed or rendering failed.
    """
    try:
        from weasyprint import HTML
    except ImportError:
        logger.error("WeasyPrint not installed. Run: pip install weasyprint")
        return False

    now_str = datetime.now().strftime("%d %b %Y, %I:%M %p")

    bg_css = ""
    if bg_image_b64:
        watermark_size = "300px" if style == "modern" else "240px"
        opacity = "0.04" if style == "modern" else "0.05"
        bg_css = f"""
        .watermark-circle {{ position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
            width: {watermark_size}; height: {watermark_size}; background-image: url('{bg_image_b64}');
            background-repeat: no-repeat; background-position: center center; background-size: cover;
            border-radius: 50%; opacity: {opacity}; z-index: 0; pointer-events: none; }}
        body > *:not(.watermark-circle) {{ position: relative; z-index: 1; }}
        """

    lb_rows_html = _build_leaderboard_rows(leaderboard, style) if leaderboard else ""
    questions_html = _build_questions_html(questions, session_polls, sections, shuffle_options, style)

    css = (_MODERN_CSS if style == "modern" else _CLASSIC_CSS).replace(
        "{title_short}", _escape_html(quiz_name[:30])
    )

    section_banner_bg = (
        "linear-gradient(135deg, #1f2937, #374151)" if style == "modern" else "linear-gradient(90deg, #374151, #4b5563)"
    )
    css = css.replace(".section-banner { column-span: all;", f".section-banner {{ column-span: all; background: {section_banner_bg};")

    watermark_div = '<div class="watermark-circle"></div>' if bg_image_b64 else ""
    leaderboard_title = '<div class="section-title">\U0001F3C6 Leaderboard</div>' if leaderboard else ""
    leaderboard_table = (
        f"""<table class="leaderboard"><thead><tr>
            <th>Rank</th><th style="text-align:left">Participant</th><th>\u2705</th><th>\u274c</th>
            <th>Score</th><th>Acc%</th><th>Time</th></tr></thead>
            <tbody>{lb_rows_html}</tbody></table>"""
        if leaderboard else ""
    )
    footer_label = "Modern Dark Edition" if style == "modern" else "Classic Dark Edition"

    html_content = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans:wght@400;600;700&family=Noto+Sans+Devanagari:wght@400;600;700&family=Merriweather:wght@700&display=swap" rel="stylesheet">
<style>{css}{bg_css}</style></head>
<body>
{watermark_div}
<div class="report-header">
  <div class="brand-sub">⚡ Powered by Akhil</div>
  <h1 class="report-title">{_escape_html(quiz_name or "Quiz Report")}</h1>
  <div class="brand-links">
    <span>🤖 Runner Bot: <a href="https://t.me/Akhil_runner_bot">@Akhil_runner_bot</a></span> |
    <span>📝 Quiz Creator: <a href="https://t.me/akhil_quize_bot">@akhil_quize_bot</a></span>
  </div>
  <div class="report-meta">
    <span>\U0001F4DA {_escape_html(chat_title)}</span> |
    <span>\U0001F4C5 {now_str}</span> |
    <span>\u2753 {len(questions)} Questions</span> |
    <span>\u2705 +{correct_mark} / \u274c -{neg}</span>
  </div>
</div>
{leaderboard_title}
{leaderboard_table}
<div class="section-title">\U0001F4CB Questions &amp; Answers</div>
<div class="questions-container">{questions_html}</div>
<div class="footer-info">Generated by <a href="https://t.me/Akhil_runner_bot">Akhil Runner Bot</a> &bull; {footer_label}</div>
</body></html>"""

    try:
        HTML(string=html_content, base_url=".").write_pdf(output_path)
        return True
    except Exception as e:
        logger.error("WeasyPrint PDF generation failed: %s", e, exc_info=True)
        return False
