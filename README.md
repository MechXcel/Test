# MechXcel Utilities

A Streamlit app containing native Python implementations of engineering utilities. The app does not depend on standalone HTML utility files.

## Utilities
- **Nozzle Cutout Generator** — generates a nozzle-to-shell profile, displays coordinates, and exports CSV.
- **Tubesheet Tube Status** — defines tubesheet rows, assigns tube status by row/range, displays the layout, and exports/imports project data.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Add a future utility
1. Create a Python module in `utilities/` with a `run()` function.
2. Import it in `app.py`.
3. Add its name and description to `UTILITIES` and add a navigation branch that calls its `run()` function.

Prepared by Himanshu Bhatt · MechXcel
https://oss.mechxcel.in
