# -*- coding: utf-8 -*-
# Streamlit UI — CV Manager (Sidebar + Provider Switch)
import os
import requests
import pandas as pd
import streamlit as st
from st_aggrid import AgGrid
import urllib.parse
import re
from difflib import get_close_matches
from utils import translate_to_english, convert_job_to_question, needs_finetune, validate_candidate_query


BASE_URL = "http://localhost:8000/cvs"
DEFAULT_API = os.getenv("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="CV Manager", page_icon="📄", layout="wide")

# ---------------- Session ----------------
if "api_base" not in st.session_state:
    st.session_state.api_base = DEFAULT_API
if "provider" not in st.session_state:
    st.session_state.provider = "deepseek"   # "deepseek" | "openai"
if "model" not in st.session_state:
    st.session_state.model = "deepseek-chat"  # default; đổi theo provider bên dưới

# ---------------- CSS ----------------
st.markdown("""
<style>
.block-container { padding-top: .5rem; padding-bottom: 2rem; }
#MainMenu {visibility: hidden;} footer {visibility: hidden;}
.sidebar .sidebar-content { background: #0b1220; }
.sidebar-title { font-weight:700; font-size:1.1rem; color:#e5e7eb; margin:.6rem 0; }
.sidebar-hint { color:#94a3b8; font-size:.9rem; }
.card { background: linear-gradient(180deg,#0f172a 0%,#0b1220 100%); border:1px solid #1f2937; border-radius:18px; padding:18px; box-shadow:0 10px 24px rgba(0,0,0,.25); }
.card-light { background:#0b1220; border:1px solid #1e293b; border-radius:14px; padding:14px; }
.sqlbox { background:#0f172a; color:#e2e8f0; border-radius:12px; padding:12px 14px; border:1px solid #1f2937; }
.badge { display:inline-flex; align-items:center; gap:.4rem; padding:.25rem .55rem; border-radius:999px; background:#0b1220; border:1px solid #1f2937; font-size:.85rem; color:#cbd5e1; }
.badge img { width:16px; height:16px; }
</style>
""", unsafe_allow_html=True)

# ---------------- Sidebar ----------------
with st.sidebar:
    st.markdown("### 📄 CV Manager")
    st.divider()

    nav = st.radio("Điều hướng", ["📤 Upload CV", "🔎 Search", "⚙️ Settings"], label_visibility="collapsed")

    st.divider()
    st.markdown("#### 🤖 Model Provider")
    colA, colB = st.columns(2)
    with colA:
        if st.checkbox("DeepSeek", value=(st.session_state.provider=="deepseek")):
            st.session_state.provider = "deepseek"
            if st.session_state.model.startswith("gpt"):
                st.session_state.model = "deepseek-chat"
    with colB:
        if st.checkbox("OpenAI", value=(st.session_state.provider=="openai")):
            st.session_state.provider = "openai"
            if not st.session_state.model.startswith("gpt"):
                st.session_state.model = "gpt-4o-mini"  # gợi ý nhẹ

    st.text_input("Model name", key="model", help="VD: deepseek-chat | gpt-4o-mini | gpt-4o | gpt-4.1-mini ...")

    st.divider()
    st.markdown("#### API Base URL")
    st.text_input(" ", key="api_base", label_visibility="collapsed", placeholder="http://localhost:8000")

# ---------------- Helpers ----------------
def provider_badge():
    if st.session_state.provider == "deepseek":
        return (
            '<span class="badge">'
            '<img src="https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/webp/deepseek.webp" />'
            'DeepSeek'
            f' · {st.session_state.model}</span>'
        )
    else:
        return (
            '<span class="badge">'
            '<img src="https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/webp/openai-light.webp" />'
            'OpenAI'
            f' · {st.session_state.model}</span>'
        )

def header():
    st.markdown("<div style='margin-top: 1.5rem'></div>", unsafe_allow_html=True)
    c1, c2 = st.columns([0.78, 0.22])
    with c1:
        st.markdown("<h1 style='margin-bottom:0.5rem;'>📄 CV Manager</h1>", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""
        <div class="card-light"><b>API</b><br>{st.session_state.api_base}</div>
        <div style="height:.4rem"></div>
        {provider_badge()}
        """, unsafe_allow_html=True)

def call_upload(file):
    url = f"{st.session_state.api_base}/cv/upload"
    try:
        resp = requests.post(url, files={"file": (file.name, file.getvalue(), "application/pdf")}, timeout=(10, 600))
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        st.error(f"Upload error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            st.error(f"Response: {e.response.text}")
        raise
    
def call_query(question):
    url = f"{st.session_state.api_base}/query"
    question_en = translate_to_english(question).strip()
    
    # --- Check query trước khi gọi API ---
    if not validate_candidate_query(question_en):
        st.warning("⚠️ Invalid query for candidate search")
        return None
    
    if needs_finetune(question_en):
        question_ft = convert_job_to_question(question_en)

    else:
        question_ft = question_en

    body = {
        "question": question_ft,
        "provider": st.session_state.provider,
        "model": st.session_state.model
    }

    try:
        resp = requests.post(url, json=body, timeout=180)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        st.error(f"Query error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            st.error(f"Response: {e.response.text}")
        return None

# ---------------- Views ----------------
def view_upload():
    header()
    st.markdown("### Upload CV (PDF)")
    st.write("Chọn **một hoặc nhiều** PDF. Backend sẽ ingest và trả **URL xem CV**.")

    up = st.file_uploader("Chọn CVs (PDF)", type=["pdf"], accept_multiple_files=True, label_visibility="collapsed")
    st.write("")
    run = st.button("Upload & Ingest", type="primary", use_container_width=True, disabled=not up)

    if not run:
        return

    files = up or []
    total = len(files)
    if total == 0:
        st.info("Hãy chọn ít nhất 1 file PDF.")
        return

    results = []
    # Khối hiển thị tiến độ và trạng thái
    status = st.empty()
    prog = st.progress(0)
    list_container = st.container()  # chỗ log ngắn từng file (tuỳ thích)

    ok = 0
    for i, f in enumerate(files, start=1):
        status.write(f"🔄 Đang xử lý **{i}/{total}**: `{f.name}` …")
        prog.progress(i/total)

        try:
            data = call_upload(f)
            ok += 1
            # gom dữ liệu hiển thị
            results.append({
                "Source file": f.name,
                "Candidate ID": data.get("candidate_id"),
                "Full name": data.get("full_name"),
                "Resume": data.get("file_url") or data.get("resume_url"),
                "Attachment ID": data.get("attachment_id"),
                "Error": None
            })
            st.toast(f"✅ {f.name} xong", icon="✅")
            with list_container:
                st.write(f"✅ `{f.name}` uploaded.")
        except Exception as e:
            results.append({
                "Source file": f.name,
                "Candidate ID": None,
                "Full name": None,
                "Resume": None,
                "Attachment ID": None,
                "Error": str(e)
            })
            st.toast(f"❌ {f.name} lỗi", icon="❌")
            with list_container:
                st.write(f"❌ `{f.name}` lỗi: {e}")

    # Hoàn tất
    prog.empty()
    if ok == total:
        status.success(f"🎉 Hoàn tất {ok}/{total} file.")
    else:
        status.warning(f"Hoàn tất {ok}/{total} file (một số file lỗi).")

    # Bảng kết quả
    st.markdown("#### Kết quả")
    df = pd.DataFrame(results)
    if "Resume" in df.columns:
        df["Resume"] = df["Resume"].apply(
            lambda u: f'<a href="{u}" target="_blank">Open</a>' if u else ""
        )

    st.markdown(
        df.to_html(escape=False, index=False),
        unsafe_allow_html=True
    )

    with st.expander("🔎 Debug uploads (raw JSON)", expanded=False):
        st.json(results)
        

# --- Lấy dữ liệu filter options ---
def extract_filter_options(rows):
    job_titles, skills, degrees, schools = set(), set(), set(), set()
    for row in rows:
        if row.get("job_title"):
            job_titles.add(row["job_title"])
        for s in row.get("skills", []):
            if s:
                skills.add(s)
        for edu in row.get("educations", []):
            if edu.get("degree"):
                degrees.add(edu["degree"])
            if edu.get("university"):
                schools.add(edu["university"])
    return sorted(job_titles), sorted(skills), sorted(degrees), sorted(schools)


def filter_ui_dynamic(df, rows):
    st.header("🔽 Bộ lọc")

    job_titles, skills, degrees, schools = extract_filter_options(rows)

    # --- Sử dụng session_state để giữ filter ---
    job_filter = st.multiselect(
        "Job Title", options=job_titles,
        default=st.session_state.get("job_filter", [])
    )
    st.session_state["job_filter"] = job_filter

    skill_filter = st.multiselect(
        "Skills", options=skills,
        default=st.session_state.get("skill_filter", [])
    )
    st.session_state["skill_filter"] = skill_filter

    degree_filter = st.multiselect(
        "Degree", options=degrees,
        default=st.session_state.get("degree_filter", [])
    )
    st.session_state["degree_filter"] = degree_filter

    school_filter = st.multiselect(
        "University", options=schools,
        default=st.session_state.get("school_filter", [])
    )
    st.session_state["school_filter"] = school_filter

    # --- Scoring function ---
    def cv_match_score(row):
        score = 0
        # Job Title
        if job_filter and row.get("job_title") in job_filter:
            score += 2 

        # Skills
        skills_list = row.get("skills", [])
        if isinstance(skills_list, str):
            skills_list = [s.strip() for s in skills_list.split(",") if s.strip()]
        elif isinstance(skills_list, list):
            skills_list = [str(s).strip() for s in skills_list if s]
        if skill_filter:
            score += sum(1 for s in skill_filter if s in skills_list)

        # Degree
        if degree_filter:
            for edu in row.get("educations", []):
                if edu.get("degree") in degree_filter:
                    score += 1
        # School
        if school_filter:
            for edu in row.get("educations", []):
                if edu.get("school") in school_filter or edu.get("university") in school_filter:
                    score += 1
        return score

    # --- Apply scoring ---
    df_scored = df.copy()
    df_scored["_match_score"] = df_scored.apply(cv_match_score, axis=1)
    df_scored = df_scored.sort_values("_match_score", ascending=False)

    # df_scored = df_scored[df_scored["_match_score"] > 0] nếu muốn lọc bớt CV không khớp


    return df_scored.drop(columns=["_match_score"])



def view_search():
    st.markdown("<div style='margin-top:2rem'></div>", unsafe_allow_html=True)
    st.header("🔍 Candidate Search")
    q = st.text_input(
        "Câu hỏi",
        placeholder="VD: Ứng viên có kỹ năng Python / Liệt kê kinh nghiệm của Marco Russo / Ứng viên > 3 năm kinh nghiệm…"
    )
    run = st.button("Run Query", type="primary", use_container_width=True)

    # Nếu query mới -> gọi API và lưu state
    if run and q.strip():
        with st.spinner("Đang thực thi..."):
            try:
                data = call_query(q.strip())
                if not data:
                    st.warning("Không có kết quả CV nào.")
                    return

                fa = data.get("final_answer", {})
                rows = fa.get("rows", [])
                cols = fa.get("columns", [])
                if not rows or not cols:
                    st.warning("Không có kết quả CV nào.")
                    return
                
                rows = [r for r in rows if r.get("email") or r.get("job_title") or r.get("skills") or r.get("educations")]

                df_original = pd.DataFrame(rows).drop_duplicates(subset=["email"], keep="first")

                # Lưu vào session_state
                st.session_state["rows"] = rows
                st.session_state["df_original"] = df_original
            except Exception as e:
                st.error(f"Lỗi khi gọi API: {e}")
                return

    # Dùng dữ liệu đã lưu nếu có
    rows = st.session_state.get("rows")
    df_original = st.session_state.get("df_original")

    if rows is None or df_original is None:
        return  

    # Chia màn hình khi có kết quả
    col_left, col_right = st.columns([0.2, 0.8])
    with col_left:
        df_filtered = filter_ui_dynamic(df_original, rows)

    with col_right:
        if "resume_url" in df_filtered.columns:
            df_filtered["resume_url"] = df_filtered["resume_url"].apply(
                lambda u: f'<a href="{u}" target="_blank">Open</a>' if u else ""
            )

        if df_filtered.empty:
            st.warning("Không còn CV nào sau khi áp dụng bộ lọc.")
        else:
            st.markdown(df_filtered.to_html(escape=False, index=False), unsafe_allow_html=True)


# ------------------------------------


def view_settings():
    header()
    st.markdown("### ⚙️ Settings")
    st.markdown(
        "- **API Base URL**: đổi ở sidebar.\n"
        "- UI gọi **Upload** ➜ `POST /cv/upload` ; **Search** ➜ `POST /query`.\n"
        "- UI gửi thêm `provider` & `model` trong body `/query` để backend chọn LLM."
    )

    

# ---------------- Router ----------------
with st.sidebar:
    pass

if "📤" in st.session_state.get("nav", ""):
    pass  # not used; we rely on 'nav' variable below

if __name__ == "__main__" or True:
    if "Upload" in nav:
        view_upload()
    elif "Search" in nav:
        view_search()
    else:
        view_settings()

# streamlit run main.py 