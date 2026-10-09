import json
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
from matplotlib.patches import Circle

COLORS = {
    "None": "#ff0000",
    "Root weld": "#ff8c00",
    "Root PT": "#ffff00",
    "Final weld": "#f2a2e8",
    "Final PT": "#50b84a",
}
DEFAULT_ROWS = [12 + i * 3 for i in range(12)]


def _default_project():
    return {"rows": DEFAULT_ROWS.copy(), "statuses": {}}


def run():
    if "ts_project" not in st.session_state:
        st.session_state.ts_project = _default_project()
    project = st.session_state.ts_project

    st.markdown("Configure the tubesheet row layout, assign statuses to tube ranges, and export project data.")

    with st.expander("1. Tubesheet definition", expanded=True):
        nrows = st.number_input(
            "Total row numbers", min_value=1, max_value=500,
            value=len(project["rows"]), key="ts_nrows"
        )
        counts_text = st.text_input(
            "Tubes per row (comma-separated)",
            value=", ".join(map(str, project["rows"])), key="ts_counts"
        )
        if st.button("Apply row definition", type="primary", use_container_width=True):
            try:
                counts = [max(0, int(x.strip())) for x in counts_text.split(",") if x.strip()]
                if len(counts) != int(nrows):
                    st.error(f"Enter exactly {int(nrows)} row counts.")
                else:
                    project.update(rows=counts, statuses={})
                    st.session_state.ts_project = project
                    st.rerun()
            except ValueError:
                st.error("Row counts must be whole numbers separated by commas.")

    rows = project["rows"]
    total = sum(rows)
    st.markdown("#### 2. Status update")
    a, b, c, d = st.columns(4)
    row_num = a.number_input("Row number", min_value=1, max_value=max(1, len(rows)), value=1, key="ts_row")
    last = max(1, rows[int(row_num) - 1])
    start = b.number_input("Start tube", min_value=1, max_value=last, value=1, key="ts_start")
    end = c.number_input("End tube", min_value=1, max_value=last, value=last, key="ts_end")
    activity = d.selectbox("Activity", list(COLORS), key="ts_activity")

    u1, u2 = st.columns(2)
    if u1.button("Update selected range", type="primary", use_container_width=True):
        if rows[int(row_num) - 1] == 0:
            st.error("This row has zero tubes.")
        else:
            for tube in range(int(start), min(int(end), last) + 1):
                project["statuses"][f"{int(row_num)}-{tube}"] = activity
            st.session_state.ts_project = project
            st.rerun()
    if u2.button("Set selected range to None", use_container_width=True):
        for tube in range(int(start), min(int(end), last) + 1):
            project["statuses"].pop(f"{int(row_num)}-{tube}", None)
        st.session_state.ts_project = project
        st.rerun()

    status_counts = {name: 0 for name in COLORS}
    for ri, count in enumerate(rows, 1):
        for ti in range(1, count + 1):
            status_counts[project["statuses"].get(f"{ri}-{ti}", "None")] += 1
    st.caption(f"Rows: {len(rows)} · Tubes: {total} · " + " · ".join(f"{k}: {v}" for k, v in status_counts.items()))

    st.markdown("#### Tubesheet layout")
    fig, ax = plt.subplots(figsize=(12, max(4, min(12, len(rows) * 0.22))))
    max_count = max([1, *rows])
    for ri, count in enumerate(rows):
        y = len(rows) - ri
        left = (max_count - count) / 2
        for ti in range(1, count + 1):
            x = left + ti
            status = project["statuses"].get(f"{ri + 1}-{ti}", "None")
            ax.add_patch(Circle((x, y), 0.43, facecolor=COLORS[status], edgecolor="#333333", linewidth=0.45))
    ax.axvline((max_count + 1) / 2, color="#78909c", linestyle="--", linewidth=0.7)
    ax.set_xlim(0, max_count + 1)
    ax.set_ylim(0, len(rows) + 1)
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    st.pyplot(fig, use_container_width=True)
    plt.close(fig)

    st.markdown("#### Legend")
    legend_cols = st.columns(len(COLORS))
    for col, (label, color) in zip(legend_cols, COLORS.items()):
        col.markdown(
            f'<span style="display:inline-block;width:12px;height:12px;background:{color};border:1px solid #555;margin-right:5px"></span>{label}',
            unsafe_allow_html=True,
        )

    flat = []
    for ri, count in enumerate(rows, 1):
        for ti in range(1, count + 1):
            flat.append({"Row": ri, "Tube ID": f"{ri}'{ti}", "Activity": project["statuses"].get(f"{ri}-{ti}", "None")})
    df = pd.DataFrame(flat, columns=["Row", "Tube ID", "Activity"])
    st.download_button("Export CSV", df.to_csv(index=False).encode("utf-8"), "tubesheet_status.csv", "text/csv")

    project_json = json.dumps({"version": 1, "rows": rows, "statuses": project["statuses"]}, indent=2)
    st.download_button("Save project (JSON)", project_json.encode("utf-8"), "tubesheet_status.json", "application/json")
    uploaded = st.file_uploader("Load project (JSON)", type=["json"], key="ts_upload")
    if uploaded is not None and st.button("Restore uploaded project"):
        try:
            loaded = json.load(uploaded)
            if not isinstance(loaded.get("rows"), list):
                raise ValueError("Project file does not contain a row definition.")
            project.update(
                rows=[max(0, int(v)) for v in loaded["rows"]],
                statuses=loaded.get("statuses", {}),
            )
            st.session_state.ts_project = project
            st.rerun()
        except Exception as exc:
            st.error(f"Could not load project: {exc}")
