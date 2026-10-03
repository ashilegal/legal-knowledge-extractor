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
@media print { body { background:#fff; } .card { border-color:#ccc; } }
"""


def _statement(st: Statement) -> str:
    basis = st.basis.value
    label = "from source" if basis == "source" else "interpretation"
    return f'<li>{escape(st.text)}<span class="tag {basis}">{label}</span></li>'


def _pages(record: AnyRecord, names: dict[str, str]) -> str:
    by_doc: dict[str, set[int]] = defaultdict(set)
    for ev in record.evidence:
        by_doc[ev.doc_id].update(ev.pages)
    parts = [f"{escape(names.get(d, d))}, p. {', '.join(map(str, sorted(p)))}"
             for d, p in by_doc.items()]
    return "Source: " + "; ".join(parts)


def _card(record: AnyRecord, names: dict[str, str], reasons: list[str] | None = None) -> str:
    f = record.fields
    out = [f'<div class="card" id="{record.record_id}">',
           f'<h4><span class="badge">{TYPE_NAMES[record.record_type]}</span>'
           f'{escape(record_title(record))}</h4>']
    if record.flags.proprietary:
        out[-1] = out[-1].replace("</h4>", '<span class="badge flag">author commentary</span></h4>')
    facts = []
    if record.record_type == "CASE":
        for label, value in (("Citation", f.citation), ("Court", f.court),
                             ("Date", f.date.value if f.date else None)):
            if value:
                facts.append((label, value))
        if f.parties:
            facts.append(("Parties", "; ".join(
                f"{p.name}{f' ({p.role})' if p.role else ''}" for p in f.parties)))
    laws = getattr(f, "laws", None) or getattr(f, "provisions", None) or []
    if laws:
        facts.append(("Law", "; ".join(" ".join(x for x in (l.provision, l.statute) if x)
                                        for l in laws)))
    for law in laws:
        if law.quoted_provision:
            facts.append(("Quoted text", f"“{law.quoted_provision}”"))
    if record.topic:
        facts.append(("Topic", record.topic.name + (f" › {record.subtopic.name}"
                                                    if record.subtopic else "")))
    if facts:
        out.append("<dl>" + "".join(f"<dt>{escape(k)}</dt><dd>{escape(str(v))}</dd>"
                                    for k, v in facts) + "</dl>")
    for name, label in LABELS.items():
        value = getattr(f, name, None)
        items = [value] if isinstance(value, Statement) else (value or [])
        items = [s for s in items if isinstance(s, Statement)]
        if items:
            out.append(f'<div class="field"><b>{label}</b><ul class="st">'
                       + "".join(_statement(s) for s in items) + "</ul></div>")
    if record.record_type == "COMPARISON" and f.items:
        rows = "".join(f"<tr><td>{escape(i.subject)}</td><td>{escape(i.attribute)}</td>"
                       f"<td>{escape(i.value)}</td></tr>" for i in f.items
                       if isinstance(i, ComparisonItem))
        out.append("<table><tr><th>Subject</th><th>Aspect</th><th>Value</th></tr>"
                   f"{rows}</table>")
    if record.record_type == "EXAMPLE" and f.concept_illustrated:
        out.append(f'<div class="field"><b>Illustrates</b> '
                   f'{escape(", ".join(f.concept_illustrated))}</div>')
    if f.related:
        out.append(f'<div class="field"><b>Related</b> '
                   f'{escape("; ".join(r.name for r in f.related))}</div>')
    out.append(f'<div class="pages">{_pages(record, names)}</div>')
    if reasons:
        out.append('<div class="reasons">Why it is waiting for review: '
                   + escape("; ".join(reasons)) + "</div>")
    out.append("</div>")
    return "\n".join(out)


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
            reviews.append((parse_record(row["data"]), json.loads(row["reasons"])))

    html = ["<!doctype html><html lang='en'><head><meta charset='utf-8'>",
            "<meta name='viewport' content='width=device-width, initial-scale=1'>",
            "<title>Knowledge Library</title>", f"<style>{CSS}</style></head><body><main>",
            "<h1>Knowledge Library</h1>",
            f"<p class='meta'>{len(records)} records from {len(names)} document(s) · "
            f"{len(reviews)} waiting for review · generated "
            f"{datetime.now():%d %b %Y %H:%M}</p>",
            "<p class='meta'>Statements are written independently from the source documents. "
            "“from source” = supported by the cited pages; “interpretation” = "
            "the system's own synthesis.</p>"]
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
        for record, reasons in reviews:
            html.append(_card(record, names, reasons))
    if not records and not reviews:
        html.append("<p>The library is empty. Run <code>lke run</code> first.</p>")
    html.append("</main></body></html>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(html), encoding="utf-8")
    return path
