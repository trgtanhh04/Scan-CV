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
    c1, c2 = st.columns([0.78, 0.22])
    with c1:
        st.title("📄 CV Manager")
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
        return None, question_en
    
    fintuned = False
    if needs_finetune(question_en):
        question_ft = convert_job_to_question(question_en)
        fintuned = True
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
        return resp.json(), question_ft, fintuned
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
            
def call_query_links(question: str):
    url = f"{st.session_state.api_base}/query"
    body = {
        "question": question,
        "provider": st.session_state.provider,
        "model": st.session_state.model,
        "links_only": True,  
    }
    try:
        resp = requests.post(url, json=body, timeout=120)
        resp.raise_for_status()
        return resp.json()    # { route, cv_links: [...] }
    except Exception as e:
        st.error(f"Links-only query error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            st.error(f"Response: {e.response.text}")
        raise

# -------------- Download & check File --------------
def _suggest_filename(name: str | None, url: str) -> str:
    # suy tên file hợp lý: <name>.pdf hoặc lấy từ URL
    if name:
        base = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip())
        return f"{base or 'resume'}.pdf"
    tail = url.split("/")[-1].split("?")[0]
    return tail or "resume.pdf"

def _force_download_url(url: str, filename: str) -> str:
    # ép header tải xuống qua query param cho GCS/CDN phổ biến
    sep = "&" if "?" in url else "?"
    disp = f"attachment%3B%20filename%3D{urllib.parse.quote(filename)}"
    return f"{url}{sep}response-content-disposition={disp}"

def view_search():
    header()
    q = st.text_input(
        "Câu hỏi",
        placeholder="VD: Ứng viên có kỹ năng Python / Liệt kê kinh nghiệm của Marco Russo / Ứng viên > 3 năm kinh nghiệm…"
    )

    col_run, col_links = st.columns([0.7, 0.3])
    with col_links:
        links_only = st.checkbox("Chỉ lấy link CV (links_only)", value=False)
    with col_run:
        run = st.button("Run Query", type="primary", use_container_width=True)

    if not (run and q.strip()):
        return

    with st.spinner("Đang thực thi..."):
        try:
            # --- LINKS ONLY ---
            if links_only:
                data = call_query_links(q.strip())
                route = data.get("route")
                links = data.get("cv_links") or []
                
                # drop trùng link
                seen = set()
                unique_links = []
                for item in links:
                    url = item.get("resume_url")
                    if url and url not in seen:
                        seen.add(url)
                        unique_links.append(item)
                links = unique_links

                st.caption(f"Route: **{route or 'UNKNOWN'}** · Tổng {len(links)} CV")

                if not links:
                    st.warning("Không có link CV nào khớp.")
                    return
                i = 1
                for item in links:
                    name = item.get("full_name") or "Unknown"
                    url  = item.get("resume_url")
                    email = item.get("email") or ""

                    st.markdown(f"### Candidate {i}")
                    i += 1
                    if email:
                        st.caption(email)

                    if not url:
                        st.warning("Không có URL CV cho ứng viên này.")
                        continue

                    # ép tải về
                    filename = _suggest_filename(item.get("full_name"), url)
                    dl_url   = _force_download_url(url, filename)

                    st.markdown(
                        f'🔗 <a href="{dl_url}" download>{dl_url}</a>',
                        unsafe_allow_html=True
                    )

                    st.markdown(
                        f"""
                        <div style="border:1px solid #1f2937; border-radius:12px; overflow:hidden; margin:10px 0;">
                          <object data="{url}" type="application/pdf" width="100%" height="560px">
                            <p>Không thể nhúng PDF (CORS). Hãy tải về qua link trên.</p>
                          </object>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                with st.expander("Raw JSON", expanded=False):
                    st.json(data)
                return

            # --- FULL SEARCH ---
            data, query_ft, fintuned = call_query(q.strip())  
            if not data:
                return
            if fintuned:
                st.markdown(f"**Query đã finetune:** `{query_ft}`")
            route = data.get("route")

            st.caption(f"🔧 route={route} | rows={len(data.get('rows') or [])}")

            # ----------------------------
            # CASE 1: SQL
            # ----------------------------
            if route == "SQL":
                sql  = data.get("sql") or "-- no sql --"
                cols = data.get("columns") or []
                rows = data.get("rows") or []
                trials = data.get("trials") or []

                st.subheader("🗄️ SQL Query")
                st.code(sql, language="sql")

                if not rows:
                    st.warning("Không tìm thấy kết quả.")
                else:
                    df = pd.DataFrame(rows, columns=cols if cols else None)
                    if "resume_url" in df.columns:
                        df["resume_url"] = df["resume_url"].apply(
                            lambda u: f"[Open]({u})" if u else ""
                        )
                    st.markdown(df.to_markdown(index=False), unsafe_allow_html=True)

                with st.expander("Trials / Diagnostics", expanded=False):
                    st.json(trials)

            # ----------------------------
            # CASE 2: VECTOR
            # ----------------------------
            elif route == "VECTOR":
                vector_query  = data.get("vector_query")
                vector_result = data.get("vector_result", []) or []

                st.subheader("🔎 Vector Query")
                st.code(vector_query or "{}", language="json")

                if not vector_result:
                    st.warning("Không tìm thấy kết quả.")
                else:
                    # Chuẩn hoá: hỗ trợ cả 2 dạng (có/không có 'payload')
                    norm_rows = []
                    for item in vector_result:
                        payload = item.get("payload", item)
                        norm_rows.append({
                            "Candidate":   payload.get("candidate_name"),
                            "Job Title":   payload.get("job_title"),
                            "Skill":       payload.get("skill"),
                            "Type":        payload.get("type"),
                            "Source File": payload.get("source_file"),
                            "Resume":      payload.get("resume_url"),
                            "Score":       round(item.get("score", 0), 4) if isinstance(item, dict) else None,
                        })

                    df = pd.DataFrame(norm_rows)
                    df = pd.DataFrame(norm_rows)
                    if not df.empty:
                        df["_has_resume"] = df["Resume"].notna() & df["Resume"].astype(str).str.len().gt(0)
                        df.sort_values(["Candidate","_has_resume"], ascending=[True, False], inplace=True)
                        df = df.drop_duplicates(subset=["Candidate"], keep="first").drop(columns=["_has_resume"])

                    # Link cột Resume
                    if "Resume" in df.columns:
                        df["Resume"] = df["Resume"].apply(
                            lambda u: f'<a href="{u}" target="_blank">Open</a>' if u else ""
                        )

                    st.markdown("#### Top matches")
                    st.markdown(df.to_html(escape=False, index=False), unsafe_allow_html=True)

                    # Nếu phần tử đầu là 'experience' thì show chi tiết
                    first_payload = vector_result[0].get("payload", vector_result[0])
                    if first_payload.get("type") == "experience":
                        st.subheader("📌 Candidate Experiences")
                        for item in vector_result:
                            p = item.get("payload", item)
                            exp = p.get("experience_detail", {}) or {}
                            title = f"{exp.get('job_title','?')} @ {exp.get('company','?')}"
                            with st.expander(title):
                                st.write(f"**Candidate:** {p.get('candidate_name')}")
                                st.write(f"**Period:** {exp.get('start_date')} - {exp.get('end_date')}")
                                st.write(f"**Description:** {exp.get('description')}")
                                if p.get("resume_url"):
                                    st.markdown(f"📂 **Resume:** [Open]({p['resume_url']})", unsafe_allow_html=True)

            else:
                st.error("Không xác định được loại kết quả (SQL/VECTOR).")

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

# streamlit run main.py 