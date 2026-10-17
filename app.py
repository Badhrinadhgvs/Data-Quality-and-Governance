"""Streamlit user interface for the Data Quality & Governance Copilot."""

import pandas as pd
import streamlit as st

from core import apply_decisions, health, infer_schema, match_records, profile
from explainer import generate_explanation

st.set_page_config(page_title="DQ Governance Copilot", page_icon="DQ", layout="wide")


def render_guide() -> None:
    st.title("Guide to Use")
    st.caption("A short walkthrough for preparing, reviewing, and exporting cleaner data.")
    st.info("This tool finds likely duplicate or inconsistent records. It does not silently change your source file: a human reviewer must approve every fix.")

    st.subheader("1. Upload a dataset")
    st.markdown("Upload a **CSV** or **Parquet** file from the Quality Workspace. The original upload is kept unchanged in the browser session. For a demonstration, use `example_data.csv`.")
    st.subheader("2. Review the schema")
    st.markdown("The app guesses each column's meaning. Check the guesses and correct them before scanning. Available types are `id`, `name`, `email`, `phone`, `date`, `city`, `numeric`, and `text`.")
    st.subheader("3. Run the quality scan")
    st.markdown("Click **Run quality scan**. The deterministic engine calculates completeness, validity, consistency, and duplicate-related signals, then creates review proposals.")
    st.subheader("4. Review each proposal")
    st.markdown("Read the masked evidence, confidence, risk, and reasoning. Choose **approve** only when the proposed change is correct. Choose **reject** when records should remain separate. Enter the reviewer name.")
    st.warning("The optional Groq explainer only explains evidence already calculated by the code. It cannot create a match, approve a fix, or bypass human review. Without an API key, a deterministic template explanation is used.")
    st.subheader("5. Apply and export")
    st.markdown("Click **Apply approved fixes and export**. A new cleaned CSV is generated for download; your uploaded source is never overwritten.")
    st.subheader("Good practice")
    st.markdown("- Remove unnecessary sensitive columns before upload.\n- Confirm ambiguous dates and names manually.\n- Treat high-risk or low-confidence proposals as review-only.\n- Test the cleaned file before loading it into production.")


def render_workspace() -> None:
    st.title("Data Quality & Governance Copilot")
    st.caption("Code detects | AI explains | Humans approve | Everything is auditable")
    if "df" not in st.session_state:
        upload = st.file_uploader("Upload a CSV or Parquet file", type=["csv", "parquet"])
        if not upload:
            st.info("Upload a dataset to begin, or open **Guide to Use** for a walkthrough.")
            return
        st.session_state.df = pd.read_parquet(upload) if upload.name.lower().endswith("parquet") else pd.read_csv(upload)
        st.session_state.schema = infer_schema(st.session_state.df)
        st.session_state.name = upload.name

    df = st.session_state.df
    st.subheader("1. Schema review")
    edited = pd.DataFrame({"column": list(st.session_state.schema), "semantic_type": list(st.session_state.schema.values())})
    edited = st.data_editor(edited, hide_index=True, disabled=["column"])
    st.session_state.schema = dict(zip(edited.column, edited.semantic_type))
    if st.button("Run quality scan", type="primary"):
        st.session_state.profile = profile(df, st.session_state.schema)
        st.session_state.matches = match_records(df, st.session_state.schema)
        st.session_state.proposals = [generate_explanation(m, df, st.session_state.schema) | m for m in st.session_state.matches]
        st.session_state.decisions = {}
    if "profile" not in st.session_state:
        return

    quality = st.session_state.profile
    dimensions = quality["dimensions"]
    columns = st.columns(5)
    for column, (label, value) in zip(columns, [("Health", health(dimensions)), *dimensions.items()]):
        column.metric(label.title(), f"{value:.1f}")
    left, right = st.columns(2)
    with left:
        st.subheader("Issues")
        st.dataframe(pd.DataFrame(quality["issues"]), use_container_width=True, hide_index=True)
    with right:
        st.subheader("Column profile")
        st.dataframe(pd.DataFrame(quality["columns"]), use_container_width=True, hide_index=True)
    st.caption("LLM explanations use masked evidence. Without GROQ_API_KEY, a safe template fallback is used.")
    st.subheader("2. Human review queue")
    for index, proposal in enumerate(st.session_state.proposals):
        with st.container(border=True):
            st.write(f"**{proposal['summary']}** | confidence `{proposal['confidence']:.2f}` | `{proposal['risk']}` risk")
            st.caption(proposal["reasoning"])
            choice = st.radio("Decision", ["pending", "approve", "reject"], horizontal=True, key=f"decision_{index}")
            if choice != "pending":
                st.session_state.decisions[str(index)] = {"decision": choice, "reviewer": st.text_input("Reviewer", "reviewer", key=f"reviewer_{index}")}
    if st.button("Apply approved fixes and export"):
        output = apply_decisions(df, st.session_state.proposals, st.session_state.decisions)
        after = health(profile(output, st.session_state.schema)["dimensions"])
        st.success(f"Created a new cleaned copy. Health: {health(dimensions):.1f} -> {after:.1f}")
        st.download_button("Download cleaned CSV", output.to_csv(index=False), "cleaned_dataset.csv", "text/csv")


page = st.sidebar.radio("Navigate", ["Quality Workspace", "Guide to Use"])
if page == "Guide to Use":
    render_guide()
else:
    render_workspace()
