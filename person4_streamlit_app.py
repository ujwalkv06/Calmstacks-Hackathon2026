"""
person4_streamlit_app.py
OWNER: Person 4

Full Streamlit app wiring together:
    person1_fragment_recovery.py  -> carving
    person2_integrity_assessment.py -> scoring
    person3_classification_ai.py  -> categorization + priority

Run with:
    streamlit run person4_streamlit_app.py
"""

import os
import json
import shutil
import tempfile
import zipfile
from datetime import datetime

import streamlit as st
import pandas as pd
import plotly.express as px

import person1_fragment_recovery as p1
import person2_integrity_assessment as p2
import person3_classification_ai as p3

# ---------------------------------------------------------------------------
# PAGE CONFIG + THEME
# ---------------------------------------------------------------------------
st.set_page_config(page_title="ForensicAI Recovery", page_icon="🛡️", layout="wide")

st.markdown("""
<style>
    .metric-card {
        background-color: #1A1F2B;
        border-radius: 10px;
        padding: 16px;
    }
    .stTabs [data-baseweb="tab"] {
        font-size: 16px;
        padding: 10px 20px;
    }
    h1, h2, h3 { letter-spacing: 0.3px; }
</style>
""", unsafe_allow_html=True)

STATUS_COLORS = {"intact": "#2ECC71", "partial": "#F1C40F", "corrupted": "#E74C3C"}

if "pipeline_ran" not in st.session_state:
    st.session_state.pipeline_ran = False
if "results" not in st.session_state:
    st.session_state.results = None
if "log_lines" not in st.session_state:
    st.session_state.log_lines = []

WORK_DIR = "recovered"
FRAGMENTS_JSON = "fragments.json"
SCORED_JSON = "fragments_scored.json"
FINAL_JSON = "fragments_final.json"

# ---------------------------------------------------------------------------
# HEADER
# ---------------------------------------------------------------------------
st.title("🛡️ ForensicAI — Intelligent Data Recovery & Evidence Reconstruction")
st.caption("AI-assisted fragment recovery, integrity scoring, and investigative prioritization")

tabs = st.tabs(["📤 Upload", "⚙️ Recovery", "📊 Results", "📄 Report"])

# ---------------------------------------------------------------------------
# TAB 1: UPLOAD
# ---------------------------------------------------------------------------
with tabs[0]:
    st.subheader("Upload storage data")
    st.write("Upload a raw disk image / byte blob (`.bin`, `.img`) **or** a `.zip` of "
             "already-separated (possibly corrupted) files.")

    uploaded_file = st.file_uploader(
        "Choose a file", type=["bin", "img", "zip", "dd", "raw"]
    )

    use_demo_data = st.checkbox(
        "Use the built-in demo dataset instead (test_data/simulated_disk_image.bin)",
        value=not bool(uploaded_file)
    )

    input_mode = None
    input_path = None

    if uploaded_file is not None and not use_demo_data:
        tmp_dir = tempfile.mkdtemp()
        input_path = os.path.join(tmp_dir, uploaded_file.name)
        with open(input_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        st.success(f"Uploaded: {uploaded_file.name} ({os.path.getsize(input_path):,} bytes)")

        if uploaded_file.name.endswith(".zip"):
            extract_dir = os.path.join(tmp_dir, "extracted")
            with zipfile.ZipFile(input_path) as z:
                z.extractall(extract_dir)
            input_mode = "folder"
            input_path = extract_dir
            st.info(f"Detected ZIP archive — will treat as a folder of {len(os.listdir(extract_dir))} file(s).")
        else:
            input_mode = "blob"

    elif use_demo_data:
        demo_path = os.path.join("test_data", "simulated_disk_image.bin")
        if os.path.exists(demo_path):
            input_mode = "blob"
            input_path = demo_path
            st.info(f"Using demo dataset: {demo_path} ({os.path.getsize(demo_path):,} bytes)")
        else:
            st.warning("Demo dataset not found. Run `python test_data_generator.py` first.")

    st.session_state.input_mode = input_mode
    st.session_state.input_path = input_path

# ---------------------------------------------------------------------------
# TAB 2: RECOVERY (runs the pipeline)
# ---------------------------------------------------------------------------
with tabs[1]:
    st.subheader("Run recovery pipeline")

    input_mode = st.session_state.get("input_mode")
    input_path = st.session_state.get("input_path")

    if not input_path:
        st.warning("Go to the Upload tab first and select or confirm a data source.")
    else:
        if st.button("▶️ Start Recovery", type="primary"):
            if os.path.exists(WORK_DIR):
                shutil.rmtree(WORK_DIR)

            progress = st.progress(0, text="Starting...")
            status_box = st.status("Running recovery pipeline...", expanded=True)

            status_box.write("**Stage 1/3 — Fragment recovery (Person 1's carver)**")
            progress.progress(10, text="Scanning for file signatures...")
            if input_mode == "blob":
                records1 = p1.run_on_blob(input_path, out_json=FRAGMENTS_JSON, out_dir=WORK_DIR)
            else:
                records1 = p1.run_on_folder(input_path, out_json=FRAGMENTS_JSON, out_dir=WORK_DIR)
            status_box.write(f"Found {len(records1)} candidate fragment(s).")
            progress.progress(40, text="Fragments recovered.")

            status_box.write("**Stage 2/3 — Integrity & corruption assessment (Person 2)**")
            progress.progress(55, text="Validating structure and computing entropy...")
            records2 = p2.assess_fragments(fragments_json=FRAGMENTS_JSON, out_json=SCORED_JSON)
            status_box.write("Integrity scoring complete.")
            progress.progress(75, text="Integrity assessment complete.")

            status_box.write("**Stage 3/3 — Classification & prioritization (Person 3 / AI layer)**")
            progress.progress(85, text="Classifying and ranking artifacts...")
            records3 = p3.classify_and_prioritize(scored_json=SCORED_JSON, out_json=FINAL_JSON)
            status_box.write(f"Classification backend: `{p3._get_backend()}`")
            progress.progress(100, text="Done.")
            status_box.update(label="Pipeline complete ✅", state="complete")

            st.session_state.results = records3
            st.session_state.pipeline_ran = True
            st.success(f"Recovered and analyzed {len(records3)} artifact(s). See the Results tab.")

        if st.session_state.pipeline_ran:
            st.info("Pipeline has already run. Click Start Recovery again to re-run on the current input.")

# ---------------------------------------------------------------------------
# TAB 3: RESULTS DASHBOARD
# ---------------------------------------------------------------------------
with tabs[2]:
    st.subheader("Results dashboard")

    if not st.session_state.pipeline_ran or not st.session_state.results:
        st.info("Run the pipeline in the Recovery tab first.")
    else:
        df = pd.DataFrame(st.session_state.results)

        total = len(df)
        intact = int((df["status"] == "intact").sum())
        partial = int((df["status"] == "partial").sum())
        corrupted = int((df["status"] == "corrupted").sum())
        high_priority = int((df["priority_score"] >= 70).sum())

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Recovered", total)
        c2.metric("Fully Intact", intact)
        c3.metric("Partially Corrupted", partial)
        c4.metric("High Priority (≥70)", high_priority)

        col_a, col_b = st.columns(2)
        with col_a:
            cat_counts = df["category"].value_counts().reset_index()
            cat_counts.columns = ["category", "count"]
            fig1 = px.pie(cat_counts, names="category", values="count",
                          title="Recovered Items by Category", hole=0.4)
            st.plotly_chart(fig1, use_container_width=True)
        with col_b:
            fig2 = px.histogram(df, x="integrity_score", nbins=10,
                                title="Integrity Score Distribution",
                                color="status", color_discrete_map=STATUS_COLORS)
            st.plotly_chart(fig2, use_container_width=True)

        st.markdown("### Recovered artifacts")
        display_cols = ["fragment_id", "detected_type", "category", "ai_label",
                        "integrity_score", "status", "priority_score", "footer_found"]
        display_cols = [c for c in display_cols if c in df.columns]
        st.dataframe(
            df[display_cols].sort_values("priority_score", ascending=False),
            use_container_width=True,
            column_config={
                "integrity_score": st.column_config.ProgressColumn(
                    "integrity_score", min_value=0, max_value=100, format="%d"),
                "priority_score": st.column_config.ProgressColumn(
                    "priority_score", min_value=0, max_value=100, format="%.1f"),
            }
        )

        st.markdown("### Inspect an artifact")
        selected_id = st.selectbox("Select fragment", df["fragment_id"].tolist())
        row = df[df["fragment_id"] == selected_id].iloc[0]

        prev_col, meta_col = st.columns([1, 2])
        with prev_col:
            fpath = row.get("file_path")
            ftype = row.get("detected_type")
            if fpath and os.path.exists(fpath):
                if ftype in ("jpeg", "png"):
                    try:
                        st.image(fpath, caption=selected_id, use_container_width=True)
                    except Exception:
                        st.write("⚠️ Preview failed — file likely corrupted.")
                elif ftype == "pdf":
                    st.write("📄 PDF recovered")
                    text = p3.extract_text(fpath, "pdf")
                    st.text(text[:500] if text else "(no extractable text)")
                elif ftype == "sqlite":
                    st.write("🗄️ SQLite database recovered")
                elif ftype == "zip_docx":
                    text = p3.extract_text(fpath, "zip_docx")
                    st.text(text[:500] if text else "(no extractable text)")
                else:
                    st.write("Binary fragment — no preview available")
        with meta_col:
            st.json({k: v for k, v in row.to_dict().items() if k != "raw"})

# ---------------------------------------------------------------------------
# TAB 4: INVESTIGATIVE DECISION SUPPORT + REPORT EXPORT
# ---------------------------------------------------------------------------
with tabs[3]:
    st.subheader("Investigative decision support & report")

    if not st.session_state.pipeline_ran or not st.session_state.results:
        st.info("Run the pipeline in the Recovery tab first.")
    else:
        df = pd.DataFrame(st.session_state.results)
        total = len(df)
        intact = int((df["status"] == "intact").sum())
        partial = int((df["status"] == "partial").sum())
        corrupted = int((df["status"] == "corrupted").sum())

        top = df.sort_values("priority_score", ascending=False).iloc[0] if total else None

        summary_lines = [
            f"Of **{total}** recovered item(s): **{intact}** are fully intact and immediately usable, "
            f"**{partial}** are partially recoverable (manual review recommended), and "
            f"**{corrupted}** are corrupted beyond confident reconstruction.",
        ]
        if top is not None:
            summary_lines.append(
                f"Highest-priority item: **{top['fragment_id']}** "
                f"({top.get('category', 'unknown')}, {top['integrity_score']}% integrity)."
            )

        recommendations = []
        borderline = df[(df["integrity_score"] >= 40) & (df["integrity_score"] < 70)]
        if len(borderline) > 0:
            recommendations.append(
                f"Manually inspect {len(borderline)} fragment(s) with 40–70% integrity score — "
                "automated confidence is moderate."
            )
        no_footer = df[df.get("footer_found", True) == False] if "footer_found" in df.columns else pd.DataFrame()
        if len(no_footer) > 0:
            recommendations.append(
                f"{len(no_footer)} fragment(s) had no footer match — likely truncated or split; "
                "consider re-scanning with a wider search window or manual carving."
            )
        if corrupted > 0:
            recommendations.append(
                f"{corrupted} fragment(s) are unlikely to be recoverable with standard techniques; "
                "consider specialized hardware-level recovery if these are critical."
            )

        st.markdown("#### Summary")
        for line in summary_lines:
            st.markdown(f"- {line}")

        if recommendations:
            st.markdown("#### Recommended next actions")
            for rec in recommendations:
                st.markdown(f"- {rec}")

        st.markdown("---")
        st.markdown("#### Export report")

        report_html = f"""
        <html><head><title>ForensicAI Recovery Report</title></head>
        <body style="font-family: sans-serif; padding: 24px;">
        <h1>ForensicAI Recovery Report</h1>
        <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        <h2>Summary</h2>
        <ul>{''.join(f'<li>{l}</li>' for l in summary_lines)}</ul>
        <h2>Recommendations</h2>
        <ul>{''.join(f'<li>{r}</li>' for r in recommendations)}</ul>
        <h2>Full Artifact List</h2>
        {df[display_cols if 'display_cols' in dir() else df.columns].to_html(index=False)}
        </body></html>
        """

        st.download_button(
            "⬇️ Download Report (HTML)",
            data=report_html,
            file_name=f"forensicai_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html",
            mime="text/html",
        )

        st.download_button(
            "⬇️ Download Raw Results (JSON)",
            data=json.dumps(st.session_state.results, indent=2, default=str),
            file_name="fragments_final.json",
            mime="application/json",
        )
