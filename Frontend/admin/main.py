# -*- coding: utf-8 -*-
# Streamlit UI — CV Manager (Sidebar + Provider Switch)
import os
import requests
import pandas as pd
import streamlit as st

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
    st.markdown('<div class="sidebar-hint">Upload ➜ Extract ➜ Search ➜ Open Resume</div>', unsafe_allow_html=True)
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
            '<img src="https://raw.githubusercontent.com/simple-icons/simple-icons/develop/icons/deepseek.svg" />'
            'DeepSeek'
            f' · {st.session_state.model}</span>'
        )
    else:
        return (
            '<span class="badge">'
            '<img src="https://raw.githubusercontent.com/simple-icons/simple-icons/develop/icons/openai.svg" />'
            'OpenAI'
            f' · {st.session_state.model}</span>'
        )

def header():
    c1, c2 = st.columns([0.78, 0.22])
    with c1:
        st.title("📄 CV Manager")
        st.caption("Upload CV ➜ Extract ➜ Store ➜ Search (Text2SQL) ➜ Open Resume")
    with c2:
        st.markdown(f"""
        <div class="card-light"><b>API</b><br>{st.session_state.api_base}</div>
        <div style="height:.4rem"></div>
        {provider_badge()}
        """, unsafe_allow_html=True)

def call_upload(file):
    url = f"{st.session_state.api_base}/cv/upload"
    resp = requests.post(url, files={"file": (file.name, file.getvalue(), "application/pdf")}, timeout=120)
    resp.raise_for_status();  return resp.json()

def call_query(question):
    """
    UI gửi thêm provider/model để backend chọn LLM:
      body = {"question": "...", "provider": "deepseek"|"openai", "model": "deepseek-chat|gpt-4o-mini|..."}
    Nếu backend bạn chưa hỗ trợ, chỉ cần bỏ qua 2 field này (UI vẫn hoạt động).
    """
    url = f"{st.session_state.api_base}/query"
    body = {"question": question, "provider": st.session_state.provider, "model": st.session_state.model}
    resp = requests.post(url, json=body, timeout=180)
    resp.raise_for_status();  return resp.json()

# ---------------- Views ----------------
def view_upload():
    header()
    st.markdown("### Upload CV (PDF)")
    st.write("Chọn **một hoặc nhiều** PDF. Backend sẽ ingest và trả **URL xem CV**.")

    up = st.file_uploader("Chọn CVs (PDF)", type=["pdf"], accept_multiple_files=True, label_visibility="collapsed")
    st.write("")
    btn = st.button("Upload & Ingest", type="primary", use_container_width=True, disabled=not up)

    if btn:
        results = []
        with st.spinner("Đang tải và xử lý..."):
            for f in up or []:
                try:
                    data = call_upload(f)
                    results.append({
                        "candidate_id": data.get("candidate_id"),
                        "full_name": data.get("full_name"),
                        "resume_url": data.get("file_url") or data.get("resume_url"),
                        "attachment_id": data.get("attachment_id"),
                        "source_file": f.name
                    })
                except Exception as e:
                    results.append({"source_file": f.name, "error": str(e)})
        st.success(f"Đã xử lý {len(results)} file.")
        st.markdown("#### Kết quả")
        df = pd.DataFrame(results)
        if "resume_url" in df.columns:
            df["resume_url"] = df["resume_url"].apply(lambda u: f"[Open]({u})" if u else "")
        st.dataframe(df, use_container_width=True, hide_index=True)

def view_search():
    header()
    st.markdown("### Search Candidates (Text2SQL)")
    q = st.text_input("Câu hỏi", placeholder="e.g. List candidates with the job title 'Software Engineer'.")
    run = st.button("Run Query", type="primary")
    if run and q.strip():
        with st.spinner("Đang sinh SQL & thực thi..."):
            try:
                data = call_query(q.strip())
                sql  = data.get("sql") or "-- no sql --"
                cols = data.get("columns", [])
                rows = data.get("rows", [])
                trials = data.get("trials", [])

                st.markdown('<div class="sqlbox">', unsafe_allow_html=True)
                st.code(sql, language="sql")
                st.markdown('</div>', unsafe_allow_html=True)

                if not rows:
                    st.warning("Không tìm thấy kết quả.")
                else:
                    df = pd.DataFrame(rows, columns=cols if cols else None)
                    if "resume_url" in df.columns:
                        df["resume_url"] = df["resume_url"].apply(lambda u: f"[Open]({u})" if u else "")
                    st.dataframe(df, use_container_width=True, hide_index=True)

                with st.expander("Trials / Diagnostics", expanded=False):
                    st.json(trials or [])
            except Exception as e:
                st.error(f"Lỗi khi gọi API: {e}")

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
