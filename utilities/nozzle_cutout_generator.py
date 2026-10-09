import math
import pandas as pd
import streamlit as st


def run():
    st.subheader("Inputs")
    c1, c2, c3, c4 = st.columns(4)
    shell = c1.number_input("Shell diameter", min_value=0.001, value=3000.0, step=100.0, key="nc_shell")
    nozzle = c2.number_input("Nozzle diameter", min_value=0.001, value=100.0, step=10.0, key="nc_nozzle")
    step = c3.number_input("Nozzle angle increment (°)", min_value=0.1, max_value=360.0, value=10.0, step=1.0, key="nc_step")
    tilt = c4.number_input("Nozzle axis tilt (°)", min_value=-89.9, max_value=89.9, value=0.0, step=1.0, key="nc_tilt")
    if nozzle > shell:
        st.error("Nozzle diameter cannot be greater than shell diameter for this calculation.")
        return

    rows = []
    R, r, beta = shell / 2, nozzle / 2, math.radians(tilt)
    count = math.ceil(360 / step)
    for i in range(count + 1):
        a = min(i * step, 360.0)
        th = math.radians(a)
        y_nozzle = r * math.cos(th)
        shell_x = math.sqrt(max(0.0, R * R - y_nozzle * y_nozzle))
        if abs(beta) < 1e-12:
            axial = r * math.sin(th)
        else:
            A = R - r * math.sin(beta) * math.sin(th)
            s = (shell_x - A) / math.cos(beta)
            axial = r * math.sin(th) * math.cos(beta) + s * math.sin(beta)
        shell_angle = math.asin(max(-1.0, min(1.0, y_nozzle / R)))
        rows.append({"Nozzle Angle (°)": a, "Shell Angle (°)": math.degrees(shell_angle), "X": R * shell_angle, "Y": axial})
        if a >= 360:
            break
    df = pd.DataFrame(rows)
    df["Spline"] = df.apply(
        lambda row: f"{row['X']:.6f}".rstrip("0").rstrip(".") + "," +
                    f"{row['Y']:.6f}".rstrip("0").rstrip("."),
        axis=1
    )
    st.markdown("#### Cutout profile")
    st.caption(f"Shell: {shell:g} · Nozzle: {nozzle:g} · Points: {len(df)}")
    st.line_chart(df.set_index("X")[["Y"]], height=400)
    st.markdown("#### Spline coordinates")
    spline = "\n".join(f"{x:.6f},{y:.6f}" for x, y in zip(df["X"], df["Y"]))
    st.text_area("Copy spline coordinates", spline, height=140, key="nc_spline")
    st.download_button("Download CSV", df.to_csv(index=False).encode("utf-8"), "nozzle_cutout.csv", "text/csv")
    st.dataframe(df, use_container_width=True, hide_index=True)
    with st.expander("Calculation notes"):
        st.markdown("""For zero tilt, the calculation follows the supplied workbook formulas:\n\n- Shell angle = asin((Nozzle Dia / Shell Dia) × cos(nozzle angle))\n- X = Shell Dia / 2 × shell angle (radians)\n- Y = sin(nozzle angle) × Nozzle Dia / 2\n\nFor a tilted nozzle, the nozzle/shell cylinder intersection is solved geometrically. Tilt is measured from the normal (perpendicular) nozzle axis, in the shell axial plane.""")
