# -*- coding: utf-8 -*-
# Streamlit UI — CV Manager (Sidebar + Provider Switch)
import os
import requests
import pandas as pd
import streamlit as st
import html
from io import BytesIO
import base64
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

    provider = st.radio("Provider", ["deepseek", "openai"], index=0 if st.session_state.provider=="deepseek" else 1)
    st.session_state.provider = provider

    if provider == "deepseek":
        st.session_state.model = "deepseek-chat"
    else:
        st.session_state.model = "gpt-4o-mini"

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
        

# ---------------- Filter helpers ----------------
def extract_filter_options(rows):
    # rows: list[dict]
    job_titles, skills, degrees, schools = set(), set(), set(), set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        jt = row.get("job_title") or row.get("Job Title")
        if jt:
            job_titles.add(jt)
        for s in row.get("skills", []) or []:
            if s:
                skills.add(s)
        for edu in row.get("educations", []) or []:
            if isinstance(edu, dict):
                d = edu.get("degree")
                u = edu.get("university") or edu.get("school")
                if d:
                    degrees.add(d)
                if u:
                    schools.add(u)
    return sorted(job_titles), sorted(skills), sorted(degrees), sorted(schools)

def render_badge_html(text, kind="skill"):
    cls = "badge"
    if kind == "skill":
        cls += " badge-skill"
    elif kind == "degree":
        cls += " badge-degree"
    elif kind == "school":
        cls += " badge-school"
    return f'<span class="{cls}">{html.escape(str(text))}</span>'

def skills_to_html(sk_list):
    if not sk_list:
        return ""
    return " ".join([render_badge_html(s, "skill") for s in sk_list if s])

def educations_to_html(edu_list):
    # edu_list: list of dict
    if not edu_list:
        return ""
    parts = []
    for edu in edu_list:
        if not isinstance(edu, dict):
            continue
        deg = edu.get("degree")
        uni = edu.get("university") or edu.get("school")
        if deg:
            parts.append(render_badge_html(deg, "degree"))
        if uni:
            parts.append(render_badge_html(uni, "school"))
    return " ".join(parts)

def filter_ui_dynamic(df, rows):
    st.markdown(
        '<div class="header-with-icon">'
        '<img src="https://cdn-icons-png.flaticon.com/512/9293/9293112.png" style="width:18px;height:18px;" />'
        '<h3 style="margin:0;color:#e6eef8">Bộ lọc</h3>'
        '</div>',
        unsafe_allow_html=True,
    )
    job_titles, skills, degrees, schools = extract_filter_options(rows)

    # default values from session_state to persist selection across reruns
    job_filter = st.multiselect("Job Title", options=job_titles, default=st.session_state.get("job_filter", []), key="ui_job")
    st.session_state["job_filter"] = job_filter
    skill_filter = st.multiselect("Skills", options=skills, default=st.session_state.get("skill_filter", []), key="ui_skill")
    st.session_state["skill_filter"] = skill_filter
    degree_filter = st.multiselect("Degree", options=degrees, default=st.session_state.get("degree_filter", []), key="ui_degree")
    st.session_state["degree_filter"] = degree_filter
    school_filter = st.multiselect("University", options=schools, default=st.session_state.get("school_filter", []), key="ui_school")
    st.session_state["school_filter"] = school_filter

    # keep original scoring logic, slightly hardened for missing fields
    def cv_match_score(row):
        score = 0
        # normalize row from pd.Series or dict-like
        job = row.get("job_title") or row.get("Job Title") or ""
        if job_filter and job in job_filter:
            score += 2
        # skills
        skills_list = row.get("skills", []) or []
        if isinstance(skills_list, str):
            skills_list = [s.strip() for s in skills_list.split(",") if s.strip()]
        elif isinstance(skills_list, list):
            skills_list = [str(s).strip() for s in skills_list if s]
        else:
            skills_list = []
        if skill_filter:
            score += sum(1 for s in skill_filter if s in skills_list)
        # degree
        if degree_filter:
            for edu in row.get("educations", []) or []:
                if isinstance(edu, dict) and edu.get("degree") in degree_filter:
                    score += 1
        # school
        if school_filter:
            for edu in row.get("educations", []) or []:
                if not isinstance(edu, dict):
                    continue
                if edu.get("school") in school_filter or edu.get("university") in school_filter:
                    score += 1
        return score

    df_scored = df.copy()
    df_scored["_match_score"] = df_scored.apply(cv_match_score, axis=1)
    df_scored = df_scored.sort_values("_match_score", ascending=False).reset_index(drop=True)
    return df_scored

# ------------------ RENDER TABLE ------------------
# def render_table_view(df: pd.DataFrame):
#     """Hiển thị CV dạng bảng."""
#     display_df = df.copy()

#     if "resume_url" in display_df.columns:
#         display_df["resume_url"] = display_df["resume_url"].apply(
#             lambda u: f'<a href="{u}" target="_blank">🔗 Open</a>' if u else ""
#         )

#     if "skills" in display_df.columns:
#         display_df["skills"] = display_df["skills"].apply(lambda s: skills_to_html(s) if s else "")
#     if "educations" in display_df.columns:
#         display_df["educations"] = display_df["educations"].apply(lambda e: educations_to_html(e) if e else "")

#     st.markdown(display_df.to_html(escape=False, index=False), unsafe_allow_html=True)

# Style chip
CHIP_STYLE = """
    <style>
    .chip {
    display: inline-block;
    padding: 4px 8px;
    margin: 2px;
    background-color: #1f2937;
    color: white;
    border-radius: 12px;
    font-size: 13px;
    text-decoration: none;
    }
    .chip:hover {
    background-color: #374151;
    }
    </style>
"""
st.markdown(CHIP_STYLE, unsafe_allow_html=True)

def chip_html(text, url=None):
    """Tạo chip HTML bo tròn."""
    if url:
        return f'<a class="chip" href="{url}" target="_blank">{text}</a>'
    return f'<span class="chip">{text}</span>'

def create_download_link(url, filename):
    """Tạo link download base64 inline."""
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            b64 = base64.b64encode(r.content).decode()
            return f'<a class="chip" href="data:application/pdf;base64,{b64}" download="{filename}">⬇️ Download</a>'
        else:
            return '<span class="chip">Lỗi</span>'
    except Exception:
        return '<span class="chip">Lỗi</span>'

def list_to_chips(val):
    """Convert list hoặc chuỗi thành chip HTML."""
    if not val:
        return ""
    if isinstance(val, list):
        return "".join([chip_html(str(v)) for v in val])
    if isinstance(val, str):
        return "".join([chip_html(v.strip()) for v in val.split(",")])
    return chip_html(str(val))


def education_to_chips(educations):
    """Format education để hiển thị rõ degree - university."""
    if not educations:
        return ""
    
    chips = []
    for edu in educations:
        # Lấy degree và university
        degree = edu.get("degree", "")
        university = edu.get("university", "")
        # Format gọn gàng
        text = degree
        if university:
            text += f" @ {university}"
        chips.append(chip_html(text))
    return "".join(chips)


def render_table_view(df: pd.DataFrame):
    """Render bảng đẹp + chip bo tròn cho Open CV và Download."""
    display_df = df.copy()

    # Open CV
    if "resume_url" in display_df.columns:
        display_df["CV"] = display_df.apply(
            lambda row: chip_html("🔗 Open", row["resume_url"]) if row["resume_url"] else "",
            axis=1
        )

    # Skills
    if "skills" in display_df.columns:
        display_df["skills"] = display_df["skills"].apply(list_to_chips)

    # Education
    # if "educations" in display_df.columns:
    #     display_df["educations"] = display_df["educations"].apply(list_to_chips)
    # Education
    if "educations" in display_df.columns:
        display_df["educations"] = display_df["educations"].apply(education_to_chips)

    # Download
    display_df["Download"] = display_df.apply(
        lambda row: create_download_link(row["resume_url"], f"{row.get('email','cv')}.pdf")
        if row.get("resume_url") else "",
        axis=1
    )

    # Cột hiển thị
    cols = [c for c in ["id", "email", "CV", "job_title", "skills", "educations", "_match_score", "Download"] if c in display_df.columns]
    display_df = display_df[cols]

    st.markdown(display_df.to_html(escape=False, index=False), unsafe_allow_html=True)



# -------------- MAIN VIEW SEARCH ------------------
def view_search():
    header()
    st.markdown("<div style='margin-top:0.6rem'></div>", unsafe_allow_html=True)

    q = st.text_input("Câu hỏi", placeholder="VD: Ứng viên có kỹ năng Python / Liệt kê kinh nghiệm...")
    run = st.button("Run Query", type="primary", use_container_width=True)

    # Fetch data from API
    if run and q and q.strip():
        with st.spinner("Đang thực thi..."):
            data = call_query(q.strip())
            if not data:
                st.warning("Không có kết quả CV nào.")
                return

            fa = data.get("final_answer", {})
            cols = fa.get("columns", []) or []
            rows_raw = fa.get("rows", []) or []

            rows = []
            for r in rows_raw:
                if isinstance(r, dict):
                    rows.append(r)
                elif isinstance(r, (list, tuple)):
                    try:
                        rows.append(dict(zip(cols, r)))
                    except Exception:
                        continue
                else:
                    continue

            # Remove empty rows
            rows = [r for r in rows if r.get("email") or r.get("job_title") or r.get("skills") or r.get("educations")]
            df_original = pd.DataFrame(rows).drop_duplicates(subset=["email"], keep="first").reset_index(drop=True)
            if df_original['id'].isnull().all():
                df_original['id'] = range(1, len(df_original) + 1)

            # Save to session
            st.session_state["rows"] = rows
            st.session_state["df_original"] = df_original

    rows = st.session_state.get("rows")
    df_original = st.session_state.get("df_original")

    if not rows or df_original is None or df_original.empty:
        st.info("Chưa có dữ liệu. Nhập câu hỏi và nhấn 'Run Query' để bắt đầu.")
        return

    # Layout: left filter, right results
    col_left, col_right = st.columns([0.28, 0.72])
    with col_left:
        df_scored = filter_ui_dynamic(df_original, rows)
        show_only_matches = st.checkbox("Chỉ hiện CV có điểm > 0", value=False, key="only_matches")
        if show_only_matches:
            df_scored = df_scored[df_scored["_match_score"] > 0].reset_index(drop=True)
        st.markdown(
            f"<div class='small-muted'>🔎 Tổng CV: <b>{len(df_original)}</b> — Sau lọc: <b>{len(df_scored)}</b></div>",
            unsafe_allow_html=True,
        )
        st.divider()
        if st.button("Export CSV (filtered)"):
            csv_bytes = df_scored.drop(columns=["_match_score"]).to_csv(index=False).encode("utf-8")
            st.download_button("Download CSV", data=csv_bytes, file_name="candidates.csv", mime="text/csv")

    with col_right:
        render_table_view(df_scored)

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