import streamlit as st
import utilities
import pkgutil
import importlib

""" add this in any next utility
TITLE = "Tool Display Name"
ICON = "⚙️"
DESCRIPTION = "Short description of what this engineering tool does."
"""

st.set_page_config(page_title="MechXcel Utilities", page_icon="⚙️", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
.block-container {padding-top:1.8rem;padding-bottom:2.5rem}
.mx-hero {padding:2rem;border-radius:16px;background:linear-gradient(125deg,#102a43,#174c70 58%,#1976a5);color:white;margin-bottom:1.25rem}
.mx-hero h1 {color:white;font-size:2.7rem;margin:0 0 .65rem}
.mx-hero p {color:#e5f3fa;font-size:1.08rem;margin:0}
</style>
""", unsafe_allow_html=True)
# Dynamically load all modules inside the utilities folder
@st.cache_resource
def load_utilities():
    discovered = {}
    for _, module_name, is_pkg in pkgutil.iter_modules(utilities.__path__):
        if not is_pkg and not module_name.startswith("_"):
            mod = importlib.import_module(f"utilities.{module_name}")
            if hasattr(mod, "run"):
                # Fallbacks if metadata is not explicitly defined in the file
                title = getattr(mod, "TITLE", module_name.replace("_", " ").title())
                icon = getattr(mod, "ICON", "⚙️")
                description = getattr(mod, "DESCRIPTION", "")
                
                discovered[title] = {
                    "icon": icon,
                    "description": description,
                    "module": mod
                }
    return discovered

UTILITIES = load_utilities()

st.sidebar.markdown("## ⚙️ MechXcel")
st.sidebar.caption("Engineering utilities")
page = st.sidebar.radio("Menu", ["Home", *UTILITIES.keys()], key="navigation")
st.sidebar.divider(); st.sidebar.markdown("**MechXcel OSS**"); st.sidebar.markdown("[oss.mechxcel.in](https://oss.mechxcel.in)")
st.sidebar.caption("Open-source tools and workflows for engineering.")
# Page Routing
if page == "Home":
    st.markdown("<section class='mx-hero'><h1>MechXcel Engineering Utilities</h1><p>Practical open-source tools for engineering workflows.</p></section>", unsafe_allow_html=True)
    st.subheader("About MechXcel OSS")
    st.markdown("Explore **[MechXcel OSS](https://oss.mechxcel.in)** for open-source engineering tools and workflows.")
    st.info("Choose an application from the left-hand menu to get started.")
    st.caption("Prepared by Himanshu Bhatt · MechXcel")
else:
    active_tool = UTILITIES[page]
    st.title(f"{active_tool['icon']} {page}")
    if active_tool["description"]:
        st.caption(active_tool["description"])
    active_tool["module"].run()
