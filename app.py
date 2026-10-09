import streamlit as st

st.set_page_config(
    page_title="MechXcel | Streamlit Test",
    page_icon="⚙️",
    layout="centered",
)

st.title("⚙️ MechXcel Engineering Utility")
st.caption("Streamlit deployment test | Python application")

st.success("If you can see this page, deployment is working!")

tab1, tab2 = st.tabs(["Unit Converter", "Hoop Stress"])

with tab1:
    st.subheader("Pressure Unit Converter")

    pressure = st.number_input(
        "Pressure value",
        min_value=0.0,
        value=10.0,
        step=1.0,
    )

    unit = st.selectbox(
        "Input unit",
        ["MPa", "bar", "psi", "kPa"],
    )

    to_mpa = {
        "MPa": 1.0,
        "bar": 0.1,
        "psi": 0.006894757,
        "kPa": 0.001,
    }

    mpa = pressure * to_mpa[unit]

    results = {
        "MPa": mpa,
        "bar": mpa * 10,
        "psi": mpa / 0.006894757,
        "kPa": mpa * 1000,
    }

    for name, value in results.items():
        st.metric(name, f"{value:,.4f}")

with tab2:
    st.subheader("Thin-Walled Cylinder Hoop Stress")

    pressure = st.number_input(
        "Internal pressure (MPa)",
        min_value=0.0,
        value=2.0,
        step=0.5,
    )

    diameter = st.number_input(
        "Internal diameter (mm)",
        min_value=0.1,
        value=1000.0,
        step=100.0,
    )

    thickness = st.number_input(
        "Wall thickness (mm)",
        min_value=0.1,
        value=10.0,
        step=1.0,
    )

    if st.button("Calculate hoop stress"):
        stress = pressure * diameter / (2 * thickness)

        st.metric(
            "Nominal hoop stress",
            f"{stress:.2f} MPa",
        )

        st.info(
            "Thin-wall estimate only. Not a pressure-vessel "
            "design calculation or code compliance check."
        )

st.divider()
st.caption("Prepared by Himanshu Bhatt | MechXcel")
