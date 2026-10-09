import streamlit as st
from utilities import nozzle_cutout_generator, tubesheet_tube_status, drawing_revision_comparator

st.set_page_config(page_title="MechXcel Utilities", page_icon="⚙️", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
.block-container {padding-top:1.8rem;padding-bottom:2.5rem}
.mx-hero {padding:2rem;border-radius:16px;background:linear-gradient(125deg,#102a43,#174c70 58%,#1976a5);color:white;margin-bottom:1.25rem}
.mx-hero h1 {color:white;font-size:2.7rem;margin:0 0 .65rem}
.mx-hero p {color:#e5f3fa;font-size:1.08rem;margin:0}
</style>
""", unsafe_allow_html=True)
UTILITIES = {
    "Nozzle Cutout Generator": {"icon":"◉", "description":"Generate nozzle-to-shell cutout profiles and spline coordinates."},
    "Tubesheet Tube Status": {"icon":"▦", "description":"Visualize a tubesheet and track tube work status."},
    "Drawing Revision Comparator": {"icon":"⇄", "description":"Compare two PDF drawing revisions and prepare a review report."},
}
st.sidebar.markdown("## ⚙️ MechXcel")
st.sidebar.caption("Engineering utilities")
page = st.sidebar.radio("Menu", ["Home", *UTILITIES.keys()], key="navigation")
st.sidebar.divider(); st.sidebar.markdown("**MechXcel OSS**"); st.sidebar.markdown("[oss.mechxcel.in](https://oss.mechxcel.in)")
st.sidebar.caption("Open-source tools and workflows for engineering.")
if page == "Home":
    st.markdown("<section class='mx-hero'><h1>MechXcel Engineering Utilities</h1><p>Practical open-source tools for engineering workflows.</p></section>", unsafe_allow_html=True)
    st.subheader("About MechXcel OSS")
    st.markdown("Explore **[MechXcel OSS](https://oss.mechxcel.in)** for open-source engineering tools and workflows.")
    st.subheader("Utilities available")
    cols = st.columns(3)
    for col,(name,info) in zip(cols,UTILITIES.items()):
        with col:
            st.markdown(f"### {info['icon']} {name}"); st.write(info["description"])
            st.button(f"Open {name}",key=f"open_{name}",use_container_width=True,on_click=lambda selected=name:st.session_state.update(navigation=selected))
    st.info("New tools are added as separate utility modules to preserve existing functionality.")
    st.caption("Prepared by Himanshu Bhatt · MechXcel")
elif page == "Nozzle Cutout Generator":
    st.title("◉ Nozzle Cutout Generator"); st.caption(UTILITIES[page]["description"]); nozzle_cutout_generator.run()
elif page == "Tubesheet Tube Status":
    st.title("▦ Tubesheet Tube Status"); st.caption(UTILITIES[page]["description"]); tubesheet_tube_status.run()
elif page == "Drawing Revision Comparator":
    st.title("⇄ Drawing Revision Comparator"); st.caption(UTILITIES[page]["description"]); drawing_revision_comparator.run()
