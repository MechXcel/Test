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


def _rapidocr_lines(page, dpi: int = 300):
    """OCR a PDF page with RapidOCR, returning text lines and an optional error.

    RapidOCR is imported lazily so native-text comparison remains available if OCR
    is disabled. It uses ONNX Runtime models distributed with rapidocr-onnxruntime;
    no separate Tesseract executable or language-data installation is required.
    """
    try:
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR

        # Cache the engine between pages/reruns where Streamlit's resource cache is available.
        engine = _get_rapidocr_engine()
        scale = dpi / 72.0
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        # PyMuPDF supplies RGB; RapidOCR/OpenCV image inputs conventionally use BGR.
        if pix.n >= 3:
            image = image[:, :, :3][:, :, ::-1].copy()
        result = engine(image)
        detections = result[0] if isinstance(result, tuple) else result
        if not detections:
            return [], ""

        # Each detection is typically [quadrilateral, text, confidence]. Group detections
        # on nearby baselines so the comparison operates on drawing text lines, not words.
        boxes = []
        for item in detections:
            if not item or len(item) < 2:
                continue
            box, text = item[0], _normalize_line(str(item[1]))
            if not text:
                continue
            ys = [float(pt[1]) for pt in box]
            xs = [float(pt[0]) for pt in box]
            height = max(1.0, max(ys) - min(ys))
            boxes.append({"y": sum(ys) / len(ys), "x": min(xs), "h": height, "text": text})
        boxes.sort(key=lambda b: (b["y"], b["x"]))
        grouped = []
        for item in boxes:
            # Use a modest baseline tolerance; do not aggressively merge adjacent rows.
            best_group = None
            best_dist = None
            for group in grouped[-4:]:
                group_y = sum(x["y"] for x in group) / len(group)
                tolerance = max(8.0, 0.45 * max(item["h"], sum(x["h"] for x in group) / len(group)))
                dist = abs(item["y"] - group_y)
                if dist <= tolerance and (best_dist is None or dist < best_dist):
                    best_group, best_dist = group, dist
            if best_group is None:
                grouped.append([item])
            else:
                best_group.append(item)
        lines = []
        for group in grouped:
            group.sort(key=lambda b: b["x"])
            line = _normalize_line(" ".join(x["text"] for x in group))
            if line:
                lines.append(line)
        return lines, ""
    except Exception as exc:
        return [], f"RapidOCR error: {exc}"


@st.cache_resource(show_spinner=False)
def _get_rapidocr_engine():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR()


def _extract_pdf(uploaded_file: Any, use_ocr: bool = False, ocr_language: str = "en", ocr_dpi: int = 300) -> dict[str, Any]:
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
            native_text = page.get_text("text", sort=True) or ""
            native_lines = [_normalize_line(x) for x in native_text.splitlines()]
            native_lines = [x for x in native_lines if x]
            ocr_used = False
            ocr_error = ""
            needs_ocr = not native_text.strip() or len("".join(native_lines)) < 35
            lines = native_lines
            extracted_text = native_text
            if use_ocr and needs_ocr:
                ocr_lines, ocr_error = _rapidocr_lines(page, dpi=ocr_dpi)
                if ocr_lines:
                    lines = ocr_lines
                    extracted_text = "\n".join(ocr_lines)
                    ocr_used = True
            pages.append({"page": n, "text": extracted_text, "lines": lines,
                          "is_textual": bool(extracted_text.strip()),
                          "native_textual": bool(native_lines), "ocr_used": ocr_used,
                          "ocr_attempted": bool(use_ocr and needs_ocr), "ocr_error": ocr_error,
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
    """Compare line multisets first, then fuzzy-pair leftovers.

    Unlike a positional sequence diff, this is resilient to PDF text-order changes
    caused by different text blocks, font encodings, or extraction order. Repeated
    identical lines are counted rather than silently collapsed.
    """
    old_by_key = {}
    new_by_key = {}
    for i, line in enumerate(old_lines, 1):
        old_by_key.setdefault(_line_key(line), []).append((i, line))
    for i, line in enumerate(new_lines, 1):
        new_by_key.setdefault(_line_key(line), []).append((i, line))

    removed, added = [], []
    all_keys = set(old_by_key) | set(new_by_key)
    for key in all_keys:
        old_items = list(old_by_key.get(key, []))
        new_items = list(new_by_key.get(key, []))
        common = min(len(old_items), len(new_items))
        removed.extend(old_items[common:])
        added.extend(new_items[common:])

    # Stable ordering makes reports easier to review. Pair similar leftovers as edits.
    removed.sort(key=lambda x: x[0])
    added.sort(key=lambda x: x[0])
    return _pair_changes(removed, added, scope, old_page, new_page)


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
    """Auto-populate a review matrix using observed differences and extraction limits.

    The statuses are heuristic triage, not engineering approval or proof that an
    item did not change. Every row remains subject to reviewer verification.
    """
    combined = "\n".join(
        str(value) for col in ("Original Text", "Revised Text")
        for value in (changes[col].tolist() if not changes.empty and col in changes else [])
    ).casefold()
    page_count_diff = len(old_doc["pages"]) != len(new_doc["pages"])
    all_pages = old_doc["pages"] + new_doc["pages"]
    unreadable_pages = [p for p in all_pages if not p["is_textual"]]
    ocr_pages = [p for p in all_pages if p.get("ocr_used")]
    ocr_errors = [p for p in all_pages if p.get("ocr_error")]
    low_text_pages = [p for p in all_pages if not p.get("native_textual", p["is_textual"])]
    any_changes = not changes.empty

    def make_item(topic, trigger, reason, priority="Routine"):
        triggered = bool(trigger)
        return {
            "Review Point": topic,
            "Application Assessment": "MANUAL REVIEW REQUIRED" if triggered else "No text trigger detected",
            "Priority": priority if triggered else "Normal",
            "Why flagged / guidance": reason if triggered else "No matching textual change was detected. Verify visually; absence of a text trigger does not prove this item is unchanged.",
            "Auto-filled": "Yes — heuristic",
        }

    dimension_trigger = bool(re.search(r"(?:\b(?:dia(?:meter)?|ø|\+/-|±|tolerance|thk|thickness|pitch|radius|\br\b|\bmm\b|\bin\b)\b|\d+(?:\.\d+)?\s*(?:mm|cm|m|in|inch|°))", combined)) and any_changes
    material_trigger = bool(re.search(r"\b(?:material|astm|asme|sa-?\d+|a-?\d{3}|grade|specification|moc|p-number|pno)\b", combined)) and any_changes
    weld_trigger = bool(re.search(r"\b(?:weld|welding|nde|ndt|rt|ut|pt|mt|pwht|heat treatment|weld map)\b", combined)) and any_changes
    pressure_trigger = bool(re.search(r"\b(?:pressure|hydrotest|hydrostatic|design temperature|design pressure|operating temperature|operating pressure|bar|mpa|psi)\b", combined)) and any_changes
    bom_trigger = bool(re.search(r"\b(?:bom|bill of materials|part no|part number|item no|quantity|qty|weight)\b", combined)) and any_changes
    revision_trigger = bool(re.search(r"\b(?:revision|rev\.?|revision history|description of change|ec[no]|ecr|issue date)\b", combined)) and any_changes

    items = [
        make_item("Drawing number, title, revision and issue date", revision_trigger or page_count_diff,
                  "A revision/title-block-like text change or page-count mismatch was detected. Compare title blocks and release metadata directly.", "High"),
        make_item("Dimensions, tolerances, units and geometric callouts", dimension_trigger,
                  "Changed text appears to contain dimension/unit terminology. Verify each value, tolerance, unit, datum and affected view against the drawing.", "High"),
        make_item("Material grades and specifications", material_trigger,
                  "Changed text appears to reference material or specification identifiers. Verify grade, material specification, condition and traceability requirements.", "High"),
        make_item("Weld details, NDE and PWHT requirements", weld_trigger,
                  "Changed text appears to reference welding or examination. Verify weld symbols, extent, method, acceptance criteria and heat-treatment notes.", "High"),
        make_item("Design/operating pressure and temperature", pressure_trigger,
                  "Changed text appears to reference pressure or temperature. Verify design basis, units, ratings and related calculations/documents.", "High"),
        make_item("BOM, part numbers and quantities", bom_trigger,
                  "Changed text appears to reference parts, quantities or BOM entries. Verify part identity, quantity, material and downstream procurement/fabrication impact.", "High"),
        make_item("Revision table and revision markers", revision_trigger,
                  "Revision-related text was changed or added/deleted. Confirm revision sequence, change description, date, approval and matching drawing markers.", "High"),
        make_item("Views, sections, details, symbols and graphical geometry", True,
                  "V1 compares extractable text only and does not inspect linework, symbols, revision clouds or geometry. Compare every view and detail visually.", "High"),
        make_item("Page completeness and scan/OCR quality", page_count_diff or bool(unreadable_pages) or bool(ocr_pages) or bool(ocr_errors) or bool(low_text_pages),
                  (f"Page count differs ({len(old_doc['pages'])} original vs {len(new_doc['pages'])} revised). " if page_count_diff else "") +
                  (f"{len(ocr_pages)} page(s) used OCR; verify recognized characters and dimensions against the page image. " if ocr_pages else "") +
                  (f"{len(unreadable_pages)} page(s) still have no extractable text. " if unreadable_pages else "") +
                  (f"OCR failed on {len(ocr_errors)} page(s); inspect these pages manually and check the RapidOCR package/model initialization. " if ocr_errors else "") +
                  "Confirm sheet numbering, inserts/deletions, and manually inspect scanned or low-text pages.", "High"),
        make_item("Referenced documents and cross-discipline impacts", any_changes,
                  "Text differences were detected. Check referenced specifications, calculations, related drawings, lists and dependent documents for consistency.", "High"),
        make_item("Reviewer disposition and release approval", True,
                  "Application-generated flags are advisory. A qualified reviewer must record disposition and follow the project's approval/release process.", "Required"),
    ]
    if not any_changes:
        items.insert(0, {
            "Review Point": "No textual differences detected",
            "Application Assessment": "MANUAL REVIEW REQUIRED",
            "Priority": "High",
            "Why flagged / guidance": "No text differences were detected, but graphical changes, scanned content, reordered text and extraction failures can be missed. Do not treat this as proof that drawings are identical.",
            "Auto-filled": "Yes — comparison result",
        })
    return items


def _make_html_report(changes, pages, checklist, old_doc, new_doc):
    def table(df):
        return "<p>No entries.</p>" if df.empty else df.to_html(index=False, escape=True, border=0, classes="data")
    counts = Counter(changes["Change Type"]) if not changes.empty else Counter()
    checklist_df = pd.DataFrame(checklist)
    checks = "<p>No checklist items.</p>" if checklist_df.empty else checklist_df.to_html(index=False, escape=True, border=0, classes="data")
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>MechXcel Drawing Revision Comparison</title>
<style>body{{font-family:Arial,sans-serif;max-width:1200px;margin:32px auto;padding:0 20px;color:#18212b}}h1{{color:#123b59}}table{{border-collapse:collapse;width:100%;font-size:12px;margin:12px 0 28px}}th,td{{border:1px solid #ccd5dd;padding:7px;text-align:left;vertical-align:top;overflow-wrap:anywhere}}th{{background:#eaf1f6}}li{{margin:8px 0}}.note{{background:#fff4d6;padding:12px;border-left:4px solid #d49a18}}</style></head><body>
<h1>MechXcel Engineering Drawing Revision Comparator</h1><p>Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} · V1 text-based comparison</p>
<div class="note"><b>Important:</b> This report compares extractable PDF text only. It does not verify graphical geometry or guarantee detection of every engineering change. Human review is required.</div>
<h2>Documents</h2><ul><li>Original: {html.escape(old_doc['name'])} ({len(old_doc['pages'])} pages)</li><li>Revised: {html.escape(new_doc['name'])} ({len(new_doc['pages'])} pages)</li></ul>
<h2>Summary</h2><p>Modified: {counts.get('Modified',0)} · Added: {counts.get('Added',0)} · Deleted: {counts.get('Deleted',0)}</p><h2>Page-by-page summary</h2>{table(pages)}<h2>Detected text changes</h2>{table(changes)}<h2>Auto-filled engineering review checklist</h2>{checks}<p>Prepared by Himanshu Bhatt · MechXcel · https://oss.mechxcel.in</p></body></html>'''


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
    story += [PageBreak(), Paragraph("Auto-filled engineering review checklist", styles["Heading2"])]
    add_table(pd.DataFrame(checklist))
    story += [Spacer(1, 2*mm), Paragraph("Assessments are heuristic prompts for manual review, not confirmation of compliance or unchanged status.", styles["BodyText"])]
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
    use_ocr = st.checkbox("Run OCR on scanned/image-based or low-text pages", value=True,
                          help="Uses RapidOCR with ONNX Runtime. The rapidocr-onnxruntime package must be in requirements.txt; model files may be downloaded on first use depending on package version.")
    ocr_dpi = st.slider("OCR rendering resolution (DPI)", min_value=150, max_value=400, value=300, step=50, disabled=not use_ocr,
                        help="Higher DPI may improve small text recognition but uses more memory and processing time.")
    if st.button("Compare drawings", type="primary", use_container_width=True):
        if old_file is None or new_file is None:
            st.error("Upload both the original and revised PDF drawings."); return
        with st.spinner("Extracting PDF text and comparing pages..."):
            try:
                old_doc = _extract_pdf(old_file, use_ocr=use_ocr, ocr_dpi=ocr_dpi)
                new_doc = _extract_pdf(new_file, use_ocr=use_ocr, ocr_dpi=ocr_dpi)
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
    all_pages = old_doc["pages"] + new_doc["pages"]
    no_text = [p for p in all_pages if not p["is_textual"]]
    ocr_used_pages = [p for p in all_pages if p.get("ocr_used")]
    ocr_failed_pages = [p for p in all_pages if p.get("ocr_error")]
    if no_text:
        st.error(f"{len(no_text)} page(s) still have no extractable text. Manual visual comparison is required for those pages.")
    if ocr_used_pages:
        st.info(f"OCR was used on {len(ocr_used_pages)} page(s). Review OCR-recognized dimensions, decimal points, minus signs, diameter symbols and material identifiers manually.")
    if ocr_failed_pages:
        st.error(f"OCR failed on {len(ocr_failed_pages)} page(s). Check that rapidocr-onnxruntime is installed and its OCR models initialize correctly; manually inspect these pages.")
    st.caption(f"Original: {old_doc['name']} · Revised: {new_doc['name']}")
    st.subheader("Page-by-page comparison"); st.dataframe(page_summary,use_container_width=True,hide_index=True)
    st.subheader("Detected changes")
    if changes.empty:
        st.success("No textual differences detected. This does not mean the drawings are identical.")
    else:
        selected = st.selectbox("Filter changes",["All","Modified","Added","Deleted"])
        st.dataframe(changes if selected=="All" else changes[changes["Change Type"]==selected],use_container_width=True,hide_index=True)
        st.download_button("Download change register (CSV)",changes.to_csv(index=False).encode("utf-8-sig"),"drawing_revision_changes.csv","text/csv")
    st.subheader("Auto-filled engineering review checklist")
    st.caption("The application assesses likely review areas from detected text changes and PDF extraction diagnostics. These are heuristic recommendations; a reviewer must verify the actual drawings.")
    checklist_df = pd.DataFrame(checklist)
    manual_only = st.checkbox("Show only points recommended for manual review", value=True, key="dr_manual_only")
    if manual_only:
        checklist_view = checklist_df[checklist_df["Application Assessment"] == "MANUAL REVIEW REQUIRED"]
    else:
        checklist_view = checklist_df
    st.dataframe(checklist_view, use_container_width=True, hide_index=True)
    st.caption(f"{int((checklist_df['Application Assessment'] == 'MANUAL REVIEW REQUIRED').sum())} review points flagged for manual review out of {len(checklist_df)} total points.")
    st.download_button("Download review checklist (CSV)", checklist_df.to_csv(index=False).encode("utf-8-sig"), "drawing_revision_review_checklist.csv", "text/csv")
    html_report = _make_html_report(changes,page_summary,checklist,old_doc,new_doc)
    pdf_report = _make_pdf_report(changes,page_summary,checklist,old_doc,new_doc)
    x,y = st.columns(2)
    x.download_button("Download HTML report",html_report.encode("utf-8"),"drawing_revision_report.html","text/html",use_container_width=True)
    y.download_button("Download PDF report",pdf_report,"drawing_revision_report.pdf","application/pdf",use_container_width=True)
    with st.expander("Text extraction diagnostics"):
        st.write("PyMuPDF extracts native PDF text. Optional OCR uses RapidOCR/ONNX Runtime on pages with no or very little native text. Revision-table detection is keyword-based and may include nearby notes. The comparison is order-independent for text lines but still does not compare drawing geometry.")
        diag=[]
        for label,doc in [("Original",old_doc),("Revised",new_doc)]:
            for p in doc["pages"]:
                diag.append({"Document":label,"Page":p["page"],"Native text":p.get("native_textual", p["is_textual"]),"OCR used":p.get("ocr_used", False),"OCR attempted":p.get("ocr_attempted", False),"OCR error":p.get("ocr_error", ""),"Extractable text":p["is_textual"],"Lines extracted":len(p["lines"]),"Page size (PDF points)":f"{p['width']} × {p['height']}"})
        st.dataframe(pd.DataFrame(diag),use_container_width=True,hide_index=True)
