# -*- coding: utf-8 -*-
# Streamlit UI — CV Manager (Sidebar + Provider Switch)
import os
import requests
import pandas as pd
import streamlit as st
import html
import re
from io import BytesIO
import io
import base64
from googleapiclient.http import MediaIoBaseDownload
from utils import translate_to_english, convert_job_to_question, needs_finetune, is_probably_english, expand_abbreviations

from utils import list_files_in_folder, extract_folder_id, get_drive_service, MIME_TYPE_FOLDER
from config import DRIVE_API_KEY


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

    nav = st.radio(
        "Điều hướng",
        ["Main","📤 Upload CV", "🔎 Search", "✉️ Invite", "⚙️ Settings"],
        label_visibility="collapsed"
    )


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


from urllib.parse import urljoin
        
def get_api_base() -> str:
    # ưu tiên session_state; nếu chưa có thì lấy từ ENV hoặc secrets
    # If user edited the sidebar widget, prefer that value.
    if "api_base" in st.session_state and st.session_state.api_base:
        return st.session_state.api_base

    # Fallback to ENV or secrets; do NOT mutate st.session_state here because the
    # widget with key 'api_base' may already be instantiated and Streamlit forbids
    # programmatic modification of a widget-key after instantiation.
    base = (
        os.getenv("API_BASE_URL", "").strip()
        or st.secrets.get("API_BASE_URL", "").strip()
    )
    if not base or not base.startswith(("http://", "https://")):
        st.error(f"API_BASE_URL chưa hợp lệ hoặc chưa cấu hình: {base!r}")
        st.stop()

    return base.rstrip("/")

def api_url(path: str) -> str:
    # ghép URL an toàn (tránh tạo ra 'https:///cv/upload')
    return urljoin(get_api_base() + "/", path.lstrip("/"))

def call_upload(file):
    # url = f"{st.session_state.api_base}/cv/upload"
    url = api_url("/cv/upload")
    try:
        st.write(f"⚙️ calling: {url}")
        resp = requests.post(url, files={"file": (file.name, file.getvalue(), "application/pdf")}, timeout=(10, 600))
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        st.error(f"Upload error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            st.error(f"Response: {e.response.text}")
        raise
    

def call_query(question):
    # url = f"{st.session_state.api_base}/query"
    url = api_url("/query")

    # Expand common abbreviations first to improve translation / fine-tuning
    question_expanded = expand_abbreviations(question)

    if is_probably_english(question_expanded):
        question_en = question_expanded.strip()
    else:
        question_en = translate_to_english(question_expanded).strip()
    
    # --- Check query trước khi gọi API ---
    # if not validate_candidate_query(question_en):
    #     st.warning("Invalid query for candidate search")
    #     return None

    if needs_finetune(question_en):
        question_ft = convert_job_to_question(question_en)
    else:
        question_ft = question_en

    body = {
        "ori_question": question,
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
    
# --- Main UI ---
def call_upload2(file_bytes: bytes, filename: str):
    # url = f"{st.session_state.api_base}/cv/upload"
    url = api_url("/cv/upload")
    try:
        st.write(f"⚙️ calling: {url}")
        resp = requests.post(url, files={"file": (filename, file_bytes.getvalue(), "application/pdf")}, timeout=(10, 600))
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        st.error(f"Upload error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            st.error(f"Response: {e.response.text}")
        raise

def upload_folder(service, folder_id, folder_name):
    try:
        # Lấy tất cả file trong folder
        files = list_files_in_folder(service, folder_id)
        docs = [f for f in files if f["mimeType"] != MIME_TYPE_FOLDER]

        if not docs:
            st.warning(f"📂 Folder {folder_name} không có CV nào để upload.")
            return

        st.info(f"🚀 Bắt đầu upload {len(docs)} CV trong folder **{folder_name}** ...")

        results = []
        for doc in docs:
            file_id = doc["id"]
            file_name = doc["name"]

            # Tải file từ Google Drive
            request = service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()

            fh.seek(0)  # reset pointer

            st.write(f"⬆️ Uploading {file_name} ...")
            try:
                resp = call_upload2(fh, file_name)  # gọi API
                results.append({"file": file_name, "status": "ok", "resp": resp})
                st.success(f"✅ {file_name} uploaded")
            except Exception as e:
                results.append({"file": file_name, "status": f"error {e}"})
                st.error(f"❌ {file_name} upload failed")

        st.success(f"🎉 Hoàn tất upload {len(results)} file!")
        return results

    except Exception as e:
        st.error(f"Upload folder error: {e}")

def view_main():
    st.title("📄 CV Manager - Public Google Drive")

    # Nếu đã load root_folder thì cho phép nhập lại
    if "root_folder" in st.session_state:
        if st.button("🔗 Nhập lại link Google Drive khác"):
            st.session_state.pop("root_folder", None)
            st.session_state.pop("current_folder", None)
            st.session_state.pop("upload_target", None)
            st.rerun()

    # Nhập link drive nếu chưa có
    if "root_folder" not in st.session_state:
        with st.form("drive_form"):
            drive_link = st.text_input("🔗 Nhập link Google Drive folder (public):")
            submitted = st.form_submit_button("Enter")

        if submitted and drive_link:
            try:
                folder_id = extract_folder_id(drive_link)
                st.session_state.root_folder = folder_id
                st.session_state.current_folder = folder_id
                st.rerun()
            except Exception as e:
                st.error(f"Lỗi: {e}")

    # Nếu đã có folder → load nội dung
    if "current_folder" in st.session_state:
        try:
            service = get_drive_service(DRIVE_API_KEY)
            files = list_files_in_folder(service, st.session_state.current_folder)

            folders = [f for f in files if f["mimeType"] == MIME_TYPE_FOLDER]
            docs = [f for f in files if f["mimeType"] != MIME_TYPE_FOLDER]

            # Chỉ hiện danh sách folder khi đang ở root_folder
            if st.session_state.current_folder == st.session_state.root_folder:
                st.subheader("📂 Danh sách Folder")

                cols = st.columns(3)
                for i, folder in enumerate(folders):
                    with cols[i % 3]:
                        with st.container(border=True):
                            c1, c2, c3 = st.columns([0.6, 0.2, 0.2])

                            # Click vào folder để mở
                            with c1:
                                if st.button(f"{folder['name']}", key=f"open_{folder['id']}", use_container_width=True):
                                    st.session_state.current_folder = folder["id"]
                                    st.rerun()

                            # Nút reload (chưa cài)
                            with c2:
                                st.button("🔄", key=f"reload_{folder['id']}", help="Reload folder", disabled=True)

                            # Nút upload DB → chỉ gắn cờ, xử lý ở ngoài
                            with c3:
                                if st.button("⬆️", key=f"upload_{folder['id']}", help="Upload vào DB"):
                                    st.session_state.upload_target = {"id": folder["id"], "name": folder["name"]}
                                    st.rerun()

                # Sau vòng lặp, check nếu có folder cần upload → xử lý ở dưới
                if "upload_target" in st.session_state:
                    folder_info = st.session_state.pop("upload_target")
                    st.markdown("---")
                    st.subheader(f"⬆️ Kết quả upload folder: {folder_info['name']}")
                    upload_folder(service, folder_info["id"], folder_info["name"])

            # Nếu đang ở folder con thì hiển thị file CV
            if st.session_state.current_folder != st.session_state.root_folder:
                st.subheader("📑 CV trong thư mục này")
                if docs:
                    for doc in docs:
                        file_link = f"https://drive.google.com/file/d/{doc['id']}/view"
                        col1, col2, col3 = st.columns([0.1, 0.7, 0.2])
                        with col1:
                            st.markdown("📄")
                        with col2:
                            st.write(doc["name"])
                        with col3:
                            st.markdown(f"[👁️ Xem]({file_link})", unsafe_allow_html=True)
                else:
                    st.info("Không có CV nào trong thư mục này.")

                if st.button("⬅️ Quay lại"):
                    st.session_state.current_folder = st.session_state.root_folder
                    st.rerun()

        except Exception as e:
            st.error(f"❌ Lỗi khi load nội dung Drive: {e}")



# def view_main():
#     st.title("📄 CV Manager - Google Drive")
#     if "root_folder" not in st.session_state:
#         with st.form("drive_form"):
#             drive_link = st.text_input("🔗 Nhập link Google Drive folder:")
#             submitted = st.form_submit_button("Enter")

#         if submitted and drive_link:
#             try:
#                 folder_id = extract_folder_id(drive_link)
#                 service = get_drive_service()
#                 st.session_state.root_folder = folder_id
#                 st.session_state.current_folder = folder_id
#                 st.rerun()
#             except Exception as e:
#                 st.error(f"Lỗi: {e}")
    

#     # Nếu đã nhập link thì load folder
#     if "current_folder" in st.session_state:
#         service = get_drive_service()
#         files = list_files_in_folder(service, st.session_state.current_folder)

#         folders = [f for f in files if f["mimeType"] == "application/vnd.google-apps.folder"]
#         docs = [f for f in files if f["mimeType"] != "application/vnd.google-apps.folder"]

#         st.subheader("📂 Danh sách Folder")

#         # Hiển thị folder theo grid 3 cột
#         cols = st.columns(3)
#         for i, folder in enumerate(folders):
#             with cols[i % 3]:
#                 with st.container(border=True):
#                     c1, c2, c3 = st.columns([0.6, 0.2, 0.2])

#                     # Tên folder ở góc trái (click để truy cập)
#                     with c1:
#                         if st.button(f" {folder['name']}", key=f"open_{folder['id']}", use_container_width=True):
#                             st.session_state.current_folder = folder["id"]
#                             st.rerun()

#                     # Nút reload
#                     with c2:
#                         if st.button("🔄", key=f"reload_{folder['id']}", help="Reload folder"):
#                             st.info(f"Reload {folder['name']} chưa được cài đặt.")

#                     # Nút upload
#                     with c3:
#                         if st.button("⬆️", key=f"upload_{folder['id']}", help="Upload vào DB"):
#                             st.info(f"Upload {folder['name']} chưa được cài đặt.")

#         # Chỉ hiển thị CV khi đang trong folder con
#         if st.session_state.current_folder != st.session_state.root_folder:
#             st.subheader("📑 CV trong thư mục này")
#             if docs:
#                 for doc in docs:
#                     file_link = f"https://drive.google.com/file/d/{doc['id']}/view"
#                     col1, col2, col3 = st.columns([0.1, 0.7, 0.2])
#                     with col1:
#                         st.markdown("📄")
#                     with col2:
#                         st.write(doc["name"])
#                     with col3:
#                         st.markdown(f"[👁️ Xem]({file_link})", unsafe_allow_html=True)
#             else:
#                 st.info("Không có CV nào trong thư mục này.")

#             if st.button("⬅️ Quay lại"):
#                 st.session_state.current_folder = st.session_state.root_folder
#                 st.rerun()

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
    job_titles, degrees, schools = set(), set(), set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        jt = row.get("job_title") or row.get("Job Title")
        if jt:
            job_titles.add(jt)
        for edu in row.get("educations", []) or []:
            if isinstance(edu, dict):
                d = edu.get("degree")
                u = edu.get("university") or edu.get("school")
                if d:
                    degrees.add(d)
                if u:
                    schools.add(u)
    return sorted(job_titles), sorted(degrees), sorted(schools)

def render_badge_html(text, kind="degree"):
    cls = "badge"
    if kind == "degree":
        cls += " badge-degree"
    elif kind == "school":
        cls += " badge-school"
    return f'<span class="{cls}">{html.escape(str(text))}</span>'

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
    job_titles, degrees, schools = extract_filter_options(rows)

    # helper: filter default values to only include options
    def filter_defaults(options, defaults):
        return [d for d in defaults if d in options]

    # job titles
    default_jobs = filter_defaults(job_titles, st.session_state.get("job_filter", []))
    job_filter = st.multiselect("Job Title", options=job_titles, default=default_jobs, key="ui_job")
    st.session_state["job_filter"] = job_filter

    # degrees
    default_degrees = filter_defaults(degrees, st.session_state.get("degree_filter", []))
    degree_filter = st.multiselect("Degree", options=degrees, default=default_degrees, key="ui_degree")
    st.session_state["degree_filter"] = degree_filter

    # schools
    default_schools = filter_defaults(schools, st.session_state.get("school_filter", []))
    school_filter = st.multiselect("University", options=schools, default=default_schools, key="ui_school")
    st.session_state["school_filter"] = school_filter

    # scoring logic (giữ nguyên)
    def cv_match_score(row):
        score = 0
        job = row.get("job_title") or row.get("Job Title") or ""
        if job_filter and job in job_filter:
            score += 2
        if degree_filter:
            for edu in row.get("educations", []) or []:
                if isinstance(edu, dict) and edu.get("degree") in degree_filter:
                    score += 1
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


def education_to_chips(val):
    """Render education thành chip với degree + university."""
    if not val:
        return ""

    chips = []
    for edu in val:
        if isinstance(edu, dict):
            degree = edu.get("degree") or ""
            university = edu.get("university") or ""
            text = degree.strip()
            if university:
                text = f"{text} @ {university}"
            chips.append(chip_html(text))
        else:
            chips.append(chip_html(str(edu)))
    return "".join(chips)


def render_table_view(df: pd.DataFrame):
    """Hiển thị CV dạng bảng."""
    display_df = df.copy()

    # Loại bỏ cột skills khỏi hiển thị
    if "skills" in display_df.columns:
        display_df = display_df.drop(columns=["skills"])

    if "resume_url" in display_df.columns:
        display_df["resume_url"] = display_df["resume_url"].apply(
            lambda u: f'<a href="{u}" target="_blank">🔗 Open</a>' if u else ""
        )

    if "educations" in display_df.columns:
        display_df["educations"] = display_df["educations"].apply(education_to_chips)

    st.markdown(display_df.to_html(escape=False, index=False), unsafe_allow_html=True)



# -------------- MAIN VIEW SEARCH ------------------
def view_search():
    header()
    st.markdown("<div style='margin-top:0.6rem'></div>", unsafe_allow_html=True)

    # top_qs = get_top_questions(3)
    # if top_qs:
    #     st.markdown("💡 <b>Gợi ý câu hỏi:</b>", unsafe_allow_html=True)
    #     cols = st.columns(len(top_qs))
    #     for i, q_text in enumerate(top_qs):
    #         if cols[i].button(q_text, key=f"suggest_{i}"):
    #             st.session_state["selected_question"] = q_text

    # if "selected_question" in st.session_state:
    #     default_q = st.session_state["selected_question"]
    # else:
    #     default_q = ""

    q = st.text_input(
        "Câu hỏi",
        placeholder="VD: Ứng viên có kỹ năng Python / Liệt kê kinh nghiệm...",
        key="q_input",
        # value=default_q
    )

    # insert_log(question=q)
    
    run = st.button("Run Query", type="primary", use_container_width=True)

    data = None
    tab1, tab2 = st.tabs(["Kết quả", "JSON Debug"])
    # Fetch data from API
    with tab1:
        if run and q and q.strip():

    # top_qs = get_top_questions(3)
    # if top_qs:
    #     st.markdown("💡 <b>Gợi ý câu hỏi gần đây:</b>", unsafe_allow_html=True)
    #     cols = st.columns(len(top_qs))
    #     for i, q_text in enumerate(top_qs):
    #         if cols[i].button(q_text, key=f"suggest_{i}"):
    #             st.session_state["q_input"] = q_text
    #             st.session_state["auto_run"] = True  # flag tự chạy luôn

    # # Text input (cho phép user gõ tay hoặc từ gợi ý)
    # q = st.text_input(
    #     "Câu hỏi",
    #     placeholder="VD: Ứng viên có kỹ năng Python / Liệt kê kinh nghiệm...",
    #     key="q_input"
    # )

    # # Nếu user bấm Run Query thủ công
    # manual_run = st.button("Run Query", type="primary", use_container_width=True)

    # # Xác định có chạy không
    # should_run = manual_run or st.session_state.get("auto_run", False)

    # data = None
    # tab1, tab2 = st.tabs(["Kết quả", "JSON Debug"])
    # # Fetch data from API
    # with tab1:
    #     if should_run and q and q.strip():

            with st.spinner("Đang thực thi..."):
                data = call_query(q.strip())
                if not data:
                    st.warning("Không có kết quả CV nào.")
                    return
                # st.json(data)  # debug
                fa = data.get("final_answer", {})
                if not isinstance(fa, dict):
                    st.warning(str(fa))
                    return
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
                rows = [r for r in rows if r.get("email") or r.get("job_title") or r.get("educations")]
                df_original = pd.DataFrame(rows).drop_duplicates(subset=["email"], keep="first").reset_index(drop=True)
                # Nếu cột id toàn bộ là None nhưng vẫn có dữ liệu, đánh số lại
                if 'id' not in df_original.columns or df_original['id'].isnull().all():
                    df_original['id'] = range(1, len(df_original) + 1)

                id_col = df_original.get('id')
                if id_col is None or id_col.isnull().all():
                    st.warning("Cột ID không tồn tại hoặc tất cả giá trị đều null")


                # Save to session
                st.session_state["rows"] = rows
                st.session_state["df_original"] = df_original
                # Persist the raw API response so the JSON Debug tab can display it
                # Do not overwrite this value unless a new query runs
                st.session_state["last_api_response"] = data

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
    with tab2:
        # Show persisted API response (if available) so it survives rerenders caused by widget interactions
        last = st.session_state.get("last_api_response")
        if last:
            st.markdown("**Persisted last API response**")
            st.json(last)
        else:
            st.info("Chưa có dữ liệu. Nhập câu hỏi và nhấn 'Run Query' để bắt đầu.")

        # Debug: show session_state keys to help diagnose when/if the key gets cleared
        with st.expander("🔧 Debug session_state (keys)", expanded=False):
            try:
                keys = list(st.session_state.keys())
                st.write(keys)
            except Exception as _:
                st.write("(unable to read session_state)")

# --------------SETTING----------------------
def view_settings():
    header()
    st.markdown("### ⚙️ Settings")
    st.markdown(
        "- **API Base URL**: đổi ở sidebar.\n"
        "- UI gọi **Upload** ➜ `POST /cv/upload` ; **Search** ➜ `POST /query`.\n"
        "- UI gửi thêm `provider` & `model` trong body `/query` để backend chọn LLM."
    )

# ------------ SEND EMAIL ----------------
def call_send_invite(candidate_email, subject, body, interview_time=None):
    url = f"{st.session_state.api_base}/invite"
    payload = {
        "email": candidate_email,
        "subject": subject,
        "body": body,
        "interview_time": interview_time
    }
    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        st.error(f"Invite error: {e}")
        return None

def invite_model(candidate):
    with st.form(f"invite_form_{candidate['id']}"):
        st.markdown(f"""
        <h3>📩 Interview Invitation for <b>{candidate['full_name']}</b></h3>
        <hr style="border:1px solid #ddd;">
        <p>Please review the details below and send the invitation email.</p>
        """, unsafe_allow_html=True)

        # Company details
        company_name = st.text_input("🏢 Company Name", value="ABC Tech Ltd.")
        hr_email = st.text_input("📧 HR Contact Email", value="hr@abctech.com")
        phone_number = st.text_input("📞 Contact Phone", value="+84 123 456 789")
        location = st.text_input("📍 Interview Location", value="123 Nguyen Trai, Hanoi")

        # Email content (HTML body)
        subject = st.text_input("✉️ Email Subject", value="Interview Invitation")
        template = st.text_area(
            "📝 Email Body (HTML Supported)",
            value=f"""
<html>
  <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <p>Dear <b>{candidate.get('full_name','')}</b>,</p>

    <p>We are pleased to invite you for an interview for the position of 
    <b>{candidate.get('job_title','')}</b> at <b>{company_name}</b>.</p>

    <table style="border-collapse: collapse; margin: 15px 0;">
      <tr><td style="padding: 6px 12px;">📅 <b>Interview Date:</b></td><td>[Choose below]</td></tr>
      <tr><td style="padding: 6px 12px;">⏰ <b>Time:</b></td><td>[Choose below]</td></tr>
      <tr><td style="padding: 6px 12px;">📍 <b>Location:</b></td><td>{location}</td></tr>
      <tr><td style="padding: 6px 12px;">📞 <b>Contact:</b></td><td>{phone_number}</td></tr>
      <tr><td style="padding: 6px 12px;">📧 <b>HR Email:</b></td><td>{hr_email}</td></tr>
    </table>

    <p>Please confirm your availability at your earliest convenience.</p>

    <p>Best regards,<br>
    <b>{company_name} Recruitment Team</b></p>
  </body>
</html>
            """.strip()
        )

        # Interview scheduling
        interview_date = st.date_input("📅 Interview Date")
        time_slot = st.selectbox("⏰ Time Slot", ["09:00", "10:00", "14:00", "16:00"])

        submitted = st.form_submit_button("📤 Send Invitation")
        if submitted:
            res = call_send_invite(
                candidate_email=candidate["email"],
                subject=subject,
                body=template,
                interview_time=f"{interview_date} {time_slot}"
            )
            if res:
                st.success("✅ Invitation email sent successfully!")
            else:
                st.error("❌ Failed to send email.")


# ---------------- Router ----------------
with st.sidebar:
    pass

if "📤" in st.session_state.get("nav", ""):
    pass  # not used; we rely on 'nav' variable below

if __name__ == "__main__" or True:

    if "Main" in nav:
        view_main()
    elif "Upload" in nav:
        view_upload()
    elif "Search" in nav:
        view_search()
    elif "Invite" in nav:
        invite_model(candidate={"id": "1", "email": "truong@example.com", "full_name": "Truong", "job_title": "Software Engineer"})

    else:
        view_settings()

# streamlit run main.py