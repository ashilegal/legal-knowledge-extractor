"""A readable copy of the library: one HTML file to open in a browser (and print to PDF)."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from html import escape
from pathlib import Path

from lke.models import AnyRecord, parse_record
from lke.models.records import ComparisonItem, Statement
from lke.store.db import Library, record_title

LABELS = {
    "material_facts": "Material facts", "legal_issues": "Legal issues", "decision": "Decision",
    "principles": "Legal principles", "important_factors": "Important factors",
    "definition": "Definition", "key_points": "Key points", "requirements": "Requirements",
    "conditions": "Conditions", "exceptions": "Exceptions", "scenario": "Scenario",
    "important_facts": "Important facts", "result": "Result",
    "key_differences": "Key differences",
}
TYPE_NAMES = {"CASE": "Case", "CONCEPT": "Concept", "RULE": "Rule / law",
              "EXAMPLE": "Example", "COMPARISON": "Comparison"}

CSS = """
:root { --bg:#fbfaf7; --card:#ffffff; --ink:#1f2328; --muted:#5d6670; --line:#e3e0d8;
        --accent:#7a4b12; --src:#2f6f3e; --int:#8a5a00; --warn:#a33a2b; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#16181b; --card:#1f2226; --ink:#e7e5e0; --muted:#a3a9b0; --line:#33373d;
          --accent:#e0b072; --src:#7fc28f; --int:#e3b45c; --warn:#ef8a7a; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
       font:15px/1.55 Georgia, 'Times New Roman', serif; }
main { max-width:960px; margin:0 auto; padding:32px 16px 64px; }
h1 { font-size:28px; margin:0 0 4px; } h2 { font-size:22px; margin:40px 0 8px;
  border-bottom:2px solid var(--accent); padding-bottom:4px; }
h3 { font-size:17px; margin:24px 0 8px; color:var(--muted); }
.meta { color:var(--muted); font-family:system-ui, sans-serif; font-size:13px; }
.toc a { color:var(--accent); text-decoration:none; } .toc li { margin:2px 0; }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px;
        padding:16px 18px; margin:12px 0; break-inside:avoid; }
.card h4 { margin:0 0 6px; font-size:17px; }
.badge { display:inline-block; font:600 11px/1 system-ui, sans-serif; letter-spacing:.04em;
         text-transform:uppercase; padding:4px 7px; border-radius:4px; margin-right:6px;
         border:1px solid var(--accent); color:var(--accent); vertical-align:2px; }
.flag { border-color:var(--warn); color:var(--warn); }
dl { margin:8px 0; display:grid; grid-template-columns:max-content 1fr; gap:2px 12px;
     font-family:system-ui, sans-serif; font-size:13px; }
dt { color:var(--muted); } dd { margin:0; }
.field { margin:10px 0 0; } .field b { font-family:system-ui, sans-serif; font-size:13px;
  color:var(--muted); text-transform:uppercase; letter-spacing:.03em; }
ul.st { margin:4px 0 0; padding-left:20px; } ul.st li { margin:3px 0; }
.tag { font:11px system-ui, sans-serif; padding:1px 5px; border-radius:3px; margin-left:4px;
       border:1px solid currentColor; }
.tag.source { color:var(--src); } .tag.interpretation { color:var(--int); }
.pages { color:var(--muted); font:12px system-ui, sans-serif; }
.reasons { color:var(--warn); font:13px system-ui, sans-serif; margin:6px 0 0; }
table { border-collapse:collapse; width:100%; font:13px system-ui, sans-serif; margin-top:6px; }
td, th { border:1px solid var(--line); padding:4px 6px; text-align:left; }
.record { background:var(--card); border:1px solid var(--line); border-radius:8px;
          margin:18px 0; overflow:hidden; break-inside:avoid; }
.record-head { background:var(--accent); color:var(--card); font:600 15px system-ui, sans-serif;
               padding:8px 14px; display:flex; justify-content:space-between; }
.record-head span { font-weight:400; font-size:12px; opacity:.85; }
table.kr { width:100%; margin:0; font:14px/1.5 Georgia, serif; }
table.kr th { width:30%; vertical-align:top; background:transparent; color:var(--muted);
              font:600 13px system-ui, sans-serif; border:0; border-bottom:1px solid var(--line);
              padding:8px 12px; }
table.kr td { border:0; border-bottom:1px solid var(--line); padding:8px 12px; }
table.kr tr:last-child th, table.kr tr:last-child td { border-bottom:0; }
table.kr ul { margin:0; padding-left:18px; } table.kr li { margin:2px 0; }
table.kr table td, table.kr table th { border:1px solid var(--line); }
.none { color:var(--muted); font-style:italic; }
.interp { color:var(--int); font:italic 12px system-ui, sans-serif; }
.quote { color:var(--muted); font-style:italic; margin-top:2px; }
.ok { color:var(--src); font-weight:600; } .review { color:var(--warn); font-weight:600; }
hr { border:0; border-top:1px dashed var(--line); margin:6px 0; }
@media (max-width:600px) { table.kr th { width:38%; } }
@media print { body { background:#fff; } .record { border-color:#999; }
  .record-head { color:#000; background:#eee; } }
"""


NOT_STATED = '<span class="none">Not stated in the source</span>'

# Field order for each record type, exactly as shown on the page.
LAYOUT = {
    "CASE": [("Case Name", "case_name"), ("Court", "court"), ("Year", "year"),
             ("Citation", "citation"), ("Parties", "parties"),
             ("Material Facts", "material_facts"), ("Legal Issue", "legal_issues"),
             ("Relevant Law", "laws"), ("Decision / Outcome", "decision"),
             ("Key Legal Principles", "principles"), ("Important Factors", "important_factors"),
             ("Related Concepts", "related_concepts"), ("Related Cases", "related_cases")],
    "CONCEPT": [("Concept Name", "concept_name"), ("Definition", "definition"),
                ("Key Points", "key_points"), ("Important Factors", "important_factors"),
                ("Related Concepts", "related_concepts"), ("Related Cases", "related_cases")],
    "RULE": [("Rule / Law Name", "rule_name"), ("Relevant Provision / Section", "provisions"),
             ("Requirements", "requirements"), ("Conditions", "conditions"),
             ("Exceptions", "exceptions"), ("Related Concepts", "related_concepts"),
             ("Related Cases", "related_cases")],
    "EXAMPLE": [("Scenario", "scenario"), ("Concept Illustrated", "concept_illustrated"),
                ("Important Facts", "important_facts"), ("Result / Conclusion", "result"),
                ("Related Concepts", "related_concepts")],
    "COMPARISON": [("Title", "title"), ("Compared", "subjects"), ("Comparison", "items"),
                   ("Key Differences", "key_differences"),
                   ("Related Concepts", "related_concepts")],
}


def _bullets(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def _statement_html(st: Statement) -> str:
    text = escape(st.text)
    if st.basis.value == "interpretation":
        text += ' <span class="interp">(interpretation)</span>'
    return text


def _page_ranges(pages: list[int]) -> str:
    """[425, 426, 427, 431] -> '425–427, 431'"""
    out, start, prev = [], None, None
    for p in sorted(set(pages)):
        if start is None:
            start = prev = p
        elif p == prev + 1:
            prev = p
        else:
            out.append(f"{start}–{prev}" if prev != start else str(start))
            start = prev = p
    if start is not None:
        out.append(f"{start}–{prev}" if prev != start else str(start))
    return ", ".join(out)


def _value(record: AnyRecord, key: str) -> str:
    f = record.fields
    if key == "year":
        return escape(f.date.value[:4]) if f.date else NOT_STATED
    if key == "parties":
        return _bullets([escape(f"{p.name}{f' ({p.role})' if p.role else ''}")
                         for p in f.parties]) if f.parties else NOT_STATED
    if key in ("laws", "provisions"):
        laws = getattr(f, key) or []
        items = []
        for law in laws:
            line = escape(", ".join(x for x in (law.provision, law.statute) if x))
            if law.quoted_provision:
                line += f'<div class="quote">“{escape(law.quoted_provision)}” (exact quote)</div>'
            items.append(line)
        return _bullets(items) if items else NOT_STATED
    if key == "related_cases":
        names = [escape(r.name) for r in f.related if r.type == "CASE"]
        return _bullets(names) if names else NOT_STATED
    if key == "related_concepts":
        names = [escape(r.name) for r in f.related if r.type != "CASE"]
        return _bullets(names) if names else NOT_STATED
    if key in ("concept_illustrated", "subjects"):
        values = getattr(f, key) or []
        return _bullets([escape(v) for v in values]) if values else NOT_STATED
    if key == "items":
        rows = "".join(f"<tr><td>{escape(i.subject)}</td><td>{escape(i.attribute)}</td>"
                       f"<td>{escape(i.value)}</td></tr>" for i in f.items
                       if isinstance(i, ComparisonItem))
        return ("<table><tr><th>Subject</th><th>Aspect</th><th>Value</th></tr>"
                f"{rows}</table>") if rows else NOT_STATED
    value = getattr(f, key, None)
    if isinstance(value, Statement):
        return _statement_html(value)
    if isinstance(value, list):
        items = [_statement_html(v) for v in value if isinstance(v, Statement)]
        if len(items) == 1 and key == "legal_issues":
            return items[0]
        return _bullets(items) if items else NOT_STATED
    return escape(str(value)) if value else NOT_STATED


def _card(record: AnyRecord, names: dict[str, str], reasons: list[str] | None = None,
          review_id: str | None = None) -> str:
    rows: list[tuple[str, str]] = [
        ("Topic", escape(record.topic.name) if record.topic else NOT_STATED),
        ("Subtopic", escape(record.subtopic.name) if record.subtopic else NOT_STATED),
        ("Content Type", TYPE_NAMES[record.record_type]),
    ]
    rows += [(label, _value(record, key)) for label, key in LAYOUT[record.record_type]]

    by_doc: dict[str, set[int]] = defaultdict(set)
    for ev in record.evidence:
        by_doc[ev.doc_id].update(ev.pages)
    refs = []
    for doc_id, pages in by_doc.items():
        refs.append(f"Document ID: {escape(doc_id)}<br>"
                    f"Document: {escape(names.get(doc_id, ''))}<br>"
                    f"Original Pages: {_page_ranges(list(pages))}")
    rows.append(("Source Reference", "<hr>".join(refs)))

    if reasons:
        status = ('<span class="review">Needs review</span><ul>'
                  + "".join(f"<li>{escape(r)}</li>" for r in reasons) + "</ul>")
    else:
        status = '<span class="ok">Validated</span>'
        if record.flags.proprietary:
            status += " · contains author commentary (flagged)"
    rows.append(("Extraction Status", status))

    body = "".join(f"<tr><th>{label}</th><td>{value}</td></tr>" for label, value in rows)
    return (f'<section class="record" id="{record.record_id}">'
            f'<div class="record-head">Knowledge Record<span>{review_id or record.record_id}'
            f'</span></div>'
            f"<table class=\"kr\">{body}</table></section>")


def export_html(lib: Library, path: Path, include_review: bool = True) -> Path:
    names = {d["doc_id"]: d["filename"] for d in lib.list_documents()}
    records = list(lib.iter_records())
    groups: dict[str, dict[str, list[AnyRecord]]] = defaultdict(lambda: defaultdict(list))
    for r in records:
        topic = r.topic.name if r.topic else "General"
        sub = r.subtopic.name if r.subtopic else ""
        groups[topic][sub].append(r)

    reviews = []
    if include_review:
        for row in lib.list_reviews("pending"):
            reviews.append((parse_record(row["data"]), json.loads(row["reasons"]),
                            row["review_id"]))

    html = ["<!doctype html><html lang='en'><head><meta charset='utf-8'>",
            "<meta name='viewport' content='width=device-width, initial-scale=1'>",
            "<title>Knowledge Library</title>", f"<style>{CSS}</style></head><body><main>",
            "<h1>Knowledge Library</h1>",
            f"<p class='meta'>{len(records)} records from {len(names)} document(s) · "
            f"{len(reviews)} waiting for review · generated "
            f"{datetime.now():%d %b %Y %H:%M}</p>",
            "<p class='meta'>Statements are written independently from the source documents and "
            "are supported by the cited pages; statements marked “(interpretation)” are the "
            "system's own synthesis.</p>"]
    if groups:
        html.append("<ul class='toc'>")
        for n, topic in enumerate(sorted(groups)):
            count = sum(len(v) for v in groups[topic].values())
            html.append(f"<li><a href='#t{n}'>{escape(topic)}</a> ({count})</li>")
        if reviews:
            html.append("<li><a href='#review'>Waiting for review</a> "
                        f"({len(reviews)})</li>")
        html.append("</ul>")
    order = {"CASE": 1, "CONCEPT": 0, "RULE": 2, "EXAMPLE": 3, "COMPARISON": 4}
    for n, topic in enumerate(sorted(groups)):
        html.append(f"<h2 id='t{n}'>{escape(topic)}</h2>")
        for sub in sorted(groups[topic]):
            if sub:
                html.append(f"<h3>{escape(sub)}</h3>")
            for r in sorted(groups[topic][sub],
                            key=lambda r: (order[r.record_type], record_title(r))):
                html.append(_card(r, names))
    if reviews:
        html.append("<h2 id='review'>Waiting for review</h2>")
        html.append("<p class='meta'>Not yet in the library. Approve with "
                    "<code>lke review approve &lt;review_id&gt;</code>.</p>")
        for record, reasons, review_id in reviews:
            html.append(_card(record, names, reasons, review_id))
    if not records and not reviews:
        html.append("<p>The library is empty. Run <code>lke run</code> first.</p>")
    html.append("</main></body></html>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(html), encoding="utf-8")
    return path
