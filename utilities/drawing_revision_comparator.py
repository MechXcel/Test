"""V1 text-based PDF revision comparison for MechXcel Engineering Utilities."""
from __future__ import annotations
import difflib, html, io, re
from collections import Counter
from datetime import datetime
from typing import Any
import pandas as pd
import streamlit as st
import fitz
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_PAGES = 500
CHANGE_COLUMNS = ["Change Type", "Scope", "Old Page", "New Page", "Original Text", "Revised Text", "Review Status"]


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.replace("\u00a0", " ").replace("\u200b", "")).strip()


def _line_key(line: str) -> str:
    return _normalize_line(line).casefold()


def _extract_pdf(uploaded_file: Any) -> dict[str, Any]:
    raw = uploaded_file.getvalue()
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("File exceeds the 100 MB limit.")
    if not raw.startswith(b"%PDF"):
        raise ValueError("The uploaded file does not appear to be a valid PDF.")
    try:
        doc = fitz.open(stream=raw, filetype="pdf")
    except Exception as exc:
        raise ValueError(f"Could not open PDF: {exc}") from exc
    try:
        if doc.page_count > MAX_PAGES:
            raise ValueError(f"PDF contains more than {MAX_PAGES} pages.")
        pages = []
        for n, page in enumerate(doc, 1):
            raw_text = page.get_text("text", sort=True) or ""
            lines = [_normalize_line(x) for x in raw_text.splitlines()]
            lines = [x for x in lines if x]
            pages.append({"page": n, "text": raw_text, "lines": lines,
                          "is_textual": bool(raw_text.strip()),
                          "width": round(page.rect.width, 2), "height": round(page.rect.height, 2)})
        meta = doc.metadata or {}
        return {"name": getattr(uploaded_file, "name", "drawing.pdf"), "pages": pages,
                "metadata": {"title": meta.get("title") or "", "author": meta.get("author") or ""},
                "bytes": len(raw)}
    finally:
        doc.close()


def _pair_changes(removed, added, scope, old_page, new_page):
    changes, remaining = [], set(range(len(added)))
    pairs = []
    for old_no, old_line in removed:
        best, best_ratio = None, 0.0
        for j in remaining:
            new_line = added[j][1]
            ratio = difflib.SequenceMatcher(None, _line_key(old_line), _line_key(new_line), autojunk=False).ratio()
            threshold = 0.58 if min(len(old_line), len(new_line)) >= 12 else 0.78
            if ratio > best_ratio and ratio >= threshold:
                best, best_ratio = j, ratio
        if best is None:
            changes.append({"Change Type":"Deleted", "Scope":scope, "Old Page":old_page, "New Page":new_page,
                            "Original Text":old_line, "Revised Text":"", "Review Status":"Not reviewed"})
        else:
            remaining.remove(best)
            pairs.append((old_line, added[best][1]))
    for old_line, new_line in pairs:
        changes.append({"Change Type":"Modified", "Scope":scope, "Old Page":old_page, "New Page":new_page,
                        "Original Text":old_line, "Revised Text":new_line, "Review Status":"Not reviewed"})
    for j, (_, new_line) in enumerate(added):
        if j in remaining:
            changes.append({"Change Type":"Added", "Scope":scope, "Old Page":old_page, "New Page":new_page,
                            "Original Text":"", "Revised Text":new_line, "Review Status":"Not reviewed"})
    return changes


def _compare_lines(old_lines, new_lines, scope, old_page, new_page):
    matcher = difflib.SequenceMatcher(None, [_line_key(x) for x in old_lines],
                                      [_line_key(x) for x in new_lines], autojunk=False)
    changes = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        removed = [(i + 1, old_lines[i]) for i in range(i1, i2)]
        added = [(j + 1, new_lines[j]) for j in range(j1, j2)]
        changes.extend(_pair_changes(removed, added, scope, old_page, new_page))
    return changes


_REV_KEYWORDS = re.compile(r"\b(rev(?:ision)?|revision history|description of change|change description|drawn by|checked by|approved by|date|ec[no]|ecr|issue)\b", re.I)

def _revision_lines(lines):
    found = []
    for i, line in enumerate(lines):
        if _REV_KEYWORDS.search(line):
            for candidate in lines[max(0, i-1):min(len(lines), i+3)]:
                if candidate not in found:
                    found.append(candidate)
    return found


def compare_documents(old_doc, new_doc, compare_revision_tables=True):
    changes, summaries = [], []
    old_pages, new_pages = old_doc["pages"], new_doc["pages"]
    for i in range(max(len(old_pages), len(new_pages))):
        op = old_pages[i] if i < len(old_pages) else None
        np = new_pages[i] if i < len(new_pages) else None
        ol, nl = (op["lines"] if op else []), (np["lines"] if np else [])
        on, nn = (op["page"] if op else "—"), (np["page"] if np else "—")
        pc = _compare_lines(ol, nl, "Page text", on, nn)
        changes.extend(pc)
        summaries.append({"Original Page":on, "Revised Page":nn, "Original Text Lines":len(ol),
                          "Revised Text Lines":len(nl), "Text Changes":len(pc),
                          "Status":("Added page" if op is None else "Deleted page" if np is None else "Changed" if pc else "No text change"),
                          "Original Has Text":bool(op and op["is_textual"]), "Revised Has Text":bool(np and np["is_textual"])})
    if compare_revision_tables:
        old_rev, new_rev = [], []
        for p in old_pages:
            old_rev.extend((p["page"], x) for x in _revision_lines(p["lines"]))
        for p in new_pages:
            new_rev.extend((p["page"], x) for x in _revision_lines(p["lines"]))
        def unique_entries(entries):
            seen, out = set(), []
            for page, line in entries:
                key = _line_key(line)
                if key not in seen:
                    seen.add(key); out.append((page, line))
            return out
        old_rev, new_rev = unique_entries(old_rev), unique_entries(new_rev)
        changes.extend(_compare_lines([x[1] for x in old_rev], [x[1] for x in new_rev], "Revision-table text",
                                      ", ".join(str(x[0]) for x in old_rev) or "—",
                                      ", ".join(str(x[0]) for x in new_rev) or "—"))
    df = pd.DataFrame(changes, columns=CHANGE_COLUMNS)
    if not df.empty:
        order = {"Modified":0, "Added":1, "Deleted":2}
        df["_order"] = df["Change Type"].map(order).fillna(9)
        df = df.sort_values(["_order", "Scope", "Old Page", "New Page"], kind="stable").drop(columns="_order").reset_index(drop=True)
    return df, pd.DataFrame(summaries)


def _build_review_items(changes, old_doc, new_doc):
    items = [
        "Confirm drawing number, title, revision and issue date in both title blocks.",
        "Review every detected text change against the actual drawing and project requirements.",
        "Verify dimensions, tolerances, units, material grades and pressure/temperature data.",
        "Check weld symbols, NDE requirements, PWHT notes and inspection/test requirements.",
        "Confirm revision clouds, delta symbols and revision-table entries are consistent.",
        "Check affected views, sections, details, BOMs and referenced documents.",
        "Confirm every page was reviewed; investigate pages with no extractable text.",
        "Record reviewer, review date and disposition before approving the revised drawing.",
    ]
    if len(old_doc["pages"]) != len(new_doc["pages"]):
        items.insert(1, "Resolve the page-count difference and verify inserted/deleted pages.")
    if any(not p["is_textual"] for p in old_doc["pages"] + new_doc["pages"]):
        items.insert(2, "One or more pages have no extractable text (possibly scanned); text comparison is incomplete.")
    if changes.empty:
        items.insert(0, "No textual differences were detected. This does not establish that the drawings are identical.")
    return items


def _make_html_report(changes, pages, checklist, old_doc, new_doc):
    def table(df):
        return "<p>No entries.</p>" if df.empty else df.to_html(index=False, escape=True, border=0, classes="data")
    counts = Counter(changes["Change Type"]) if not changes.empty else Counter()
    checks = "".join(f"<li>{html.escape(item)}</li>" for item in checklist)
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>MechXcel Drawing Revision Comparison</title>
<style>body{{font-family:Arial,sans-serif;max-width:1200px;margin:32px auto;padding:0 20px;color:#18212b}}h1{{color:#123b59}}table{{border-collapse:collapse;width:100%;font-size:12px;margin:12px 0 28px}}th,td{{border:1px solid #ccd5dd;padding:7px;text-align:left;vertical-align:top;overflow-wrap:anywhere}}th{{background:#eaf1f6}}li{{margin:8px 0}}.note{{background:#fff4d6;padding:12px;border-left:4px solid #d49a18}}</style></head><body>
<h1>MechXcel Engineering Drawing Revision Comparator</h1><p>Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} · V1 text-based comparison</p>
<div class="note"><b>Important:</b> This report compares extractable PDF text only. It does not verify graphical geometry or guarantee detection of every engineering change. Human review is required.</div>
<h2>Documents</h2><ul><li>Original: {html.escape(old_doc['name'])} ({len(old_doc['pages'])} pages)</li><li>Revised: {html.escape(new_doc['name'])} ({len(new_doc['pages'])} pages)</li></ul>
<h2>Summary</h2><p>Modified: {counts.get('Modified',0)} · Added: {counts.get('Added',0)} · Deleted: {counts.get('Deleted',0)}</p><h2>Page-by-page summary</h2>{table(pages)}<h2>Detected text changes</h2>{table(changes)}<h2>Engineering review checklist</h2><ul>{checks}</ul><p>Prepared by Himanshu Bhatt · MechXcel · https://oss.mechxcel.in</p></body></html>'''


def _make_pdf_report(changes, pages, checklist, old_doc, new_doc):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), rightMargin=10*mm, leftMargin=10*mm, topMargin=10*mm, bottomMargin=10*mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SmallCell", parent=styles["BodyText"], fontSize=6.5, leading=7.5, wordWrap="CJK"))
    story = [Paragraph("MechXcel Engineering Drawing Revision Comparator", styles["Title"]),
             Paragraph(f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} · V1 text-based comparison", styles["Normal"]), Spacer(1, 4*mm),
             Paragraph("<b>Important:</b> Text comparison only. Graphical changes and scanned text may not be detected. Engineering review is required.", styles["BodyText"]), Spacer(1, 3*mm),
             Paragraph(f"<b>Original:</b> {html.escape(old_doc['name'])} ({len(old_doc['pages'])} pages)<br/><b>Revised:</b> {html.escape(new_doc['name'])} ({len(new_doc['pages'])} pages)", styles["BodyText"]),
             Spacer(1, 4*mm), Paragraph("Page-by-page summary", styles["Heading2"])]
    def add_table(df):
        if df.empty:
            story.append(Paragraph("No entries.", styles["BodyText"])); return
        data = [[Paragraph(html.escape(str(c)), styles["SmallCell"]) for c in df.columns]]
        for row in df.fillna("").itertuples(index=False, name=None):
            data.append([Paragraph(html.escape(str(v)), styles["SmallCell"]) for v in row])
        t = Table(data, colWidths=[doc.width/len(df.columns)]*len(df.columns), repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#eaf1f6")),("GRID",(0,0),(-1,-1),0.3,colors.grey),("VALIGN",(0,0),(-1,-1),"TOP"),("LEFTPADDING",(0,0),(-1,-1),3),("RIGHTPADDING",(0,0),(-1,-1),3)]))
        story.append(t)
    add_table(pages)
    story += [Spacer(1, 4*mm), Paragraph("Detected text changes", styles["Heading2"])]
    add_table(changes)
    story += [PageBreak(), Paragraph("Engineering review checklist", styles["Heading2"])]
    for item in checklist:
        story += [Paragraph("&#9744; " + html.escape(item), styles["BodyText"]), Spacer(1, 2*mm)]
    story += [Spacer(1, 4*mm), Paragraph("Prepared by Himanshu Bhatt · MechXcel · oss.mechxcel.in", styles["Normal"])]
    doc.build(story)
    return buf.getvalue()


def run():
    st.markdown("Compare two PDF drawing revisions using extracted text, page-by-page differences and heuristic revision-table matching.")
    st.warning("Engineering review aid only. Scanned pages, graphical dimensions, symbols, linework and text-layout changes may not be detected. Verify drawings visually.")
    left, right = st.columns(2)
    with left:
        old_file = st.file_uploader("Original / previous revision (PDF)", type=["pdf"], key="dr_old")
    with right:
        new_file = st.file_uploader("Revised / current revision (PDF)", type=["pdf"], key="dr_new")
    include_revision = st.checkbox("Include heuristic revision-table comparison", value=True)
    if st.button("Compare drawings", type="primary", use_container_width=True):
        if old_file is None or new_file is None:
            st.error("Upload both the original and revised PDF drawings."); return
        with st.spinner("Extracting PDF text and comparing pages..."):
            try:
                old_doc, new_doc = _extract_pdf(old_file), _extract_pdf(new_file)
                changes, page_summary = compare_documents(old_doc, new_doc, include_revision)
                checklist = _build_review_items(changes, old_doc, new_doc)
                st.session_state["dr_result"] = {"old_doc":old_doc,"new_doc":new_doc,"changes":changes,"page_summary":page_summary,"checklist":checklist}
            except ValueError as exc:
                st.error(str(exc)); return
            except Exception as exc:
                st.error(f"Comparison failed: {exc}"); return
    result = st.session_state.get("dr_result")
    if not result:
        st.info("Upload two PDFs and select **Compare drawings** to start."); return
    changes, page_summary = result["changes"], result["page_summary"]
    old_doc, new_doc, checklist = result["old_doc"], result["new_doc"], result["checklist"]
    counts = Counter(changes["Change Type"]) if not changes.empty else Counter()
    st.divider(); st.subheader("Comparison summary")
    a,b,c,d = st.columns(4); a.metric("Modified entries",counts.get("Modified",0)); b.metric("Added entries",counts.get("Added",0)); c.metric("Deleted entries",counts.get("Deleted",0)); d.metric("Pages compared",len(page_summary))
    if any(not p["is_textual"] for p in old_doc["pages"] + new_doc["pages"]):
        st.error("At least one page has no extractable text. Text comparison is incomplete; inspect these pages manually.")
    st.caption(f"Original: {old_doc['name']} · Revised: {new_doc['name']}")
    st.subheader("Page-by-page comparison"); st.dataframe(page_summary,use_container_width=True,hide_index=True)
    st.subheader("Detected changes")
    if changes.empty:
        st.success("No textual differences detected. This does not mean the drawings are identical.")
    else:
        selected = st.selectbox("Filter changes",["All","Modified","Added","Deleted"])
        st.dataframe(changes if selected=="All" else changes[changes["Change Type"]==selected],use_container_width=True,hide_index=True)
        st.download_button("Download change register (CSV)",changes.to_csv(index=False).encode("utf-8-sig"),"drawing_revision_changes.csv","text/csv")
    st.subheader("Engineering review checklist")
    checked = [st.checkbox(item,key=f"dr_check_{i}") for i,item in enumerate(checklist)]
    st.caption(f"Checklist completed: {sum(checked)} of {len(checked)}")
    checklist_report = [("[x] " if yes else "[ ] ")+item for yes,item in zip(checked,checklist)]
    html_report = _make_html_report(changes,page_summary,checklist_report,old_doc,new_doc)
    pdf_report = _make_pdf_report(changes,page_summary,checklist_report,old_doc,new_doc)
    x,y = st.columns(2)
    x.download_button("Download HTML report",html_report.encode("utf-8"),"drawing_revision_report.html","text/html",use_container_width=True)
    y.download_button("Download PDF report",pdf_report,"drawing_revision_report.pdf","application/pdf",use_container_width=True)
    with st.expander("Text extraction diagnostics"):
        st.write("PyMuPDF extracts PDF text. Revision-table detection is keyword-based and may include nearby notes.")
        diag=[]
        for label,doc in [("Original",old_doc),("Revised",new_doc)]:
            for p in doc["pages"]:
                diag.append({"Document":label,"Page":p["page"],"Extractable text":p["is_textual"],"Lines extracted":len(p["lines"]),"Page size (PDF points)":f"{p['width']} × {p['height']}"})
        st.dataframe(pd.DataFrame(diag),use_container_width=True,hide_index=True)
