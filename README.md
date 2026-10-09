# MechXcel Engineering Utilities — Drawing Comparator V1

Adds a **Drawing Revision Comparator** as a separate utility module. The existing Nozzle Cutout Generator and Tubesheet Tube Status modules are retained and remain available in the menu.

## V1 features
- Upload original and revised PDFs.
- Extract text page-by-page with PyMuPDF.
- Report added, deleted and likely modified text entries.
- Compare page-level text and page counts.
- Heuristically extract revision-table-related text using keywords.
- Show extraction diagnostics and warn when pages have no extractable text.
- Engineering review checklist.
- Download CSV change register, HTML report and PDF report.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Important limitations
This is a text-based V1. It does not compare vector geometry or visual page content. Scanned pages, graphical dimensions/symbols, layout shifts and text extraction order can cause missed changes or noise. Revision-table detection is heuristic. A human reviewer must verify the drawings; the report is not a certification of completeness or code compliance.

## Files changed/added in this package
- `utilities/drawing_revision_comparator.py` — new tool.
- `app.py` — adds the new import, navigation entry and home card while retaining the two existing tools.
- `requirements.txt` — adds PyMuPDF and ReportLab.

Prepared by Himanshu Bhatt · MechXcel · https://oss.mechxcel.in
