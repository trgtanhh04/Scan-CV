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
    st.session_state.provider = "deepseek"
if "model" not in st.session_state:
    st.session_state.model = "deepseek-chat"

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
        ["✉️ Main", "🗂️ Drive Upload", "🔎 Search", "🔽 Filter Search", "✉️ Invite"],
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
    st.markdown("<h1 style='margin-bottom:0.5rem;'>📄 CV Manager</h1>", unsafe_allow_html=True)


from urllib.parse import urljoin
        
def get_api_base() -> str:
    if "api_base" in st.session_state and st.session_state.api_base:
        return st.session_state.api_base
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
    
def call_FilterQuery(payload: dict):
    try:
        url = api_url("/filter_query")
        res = requests.post(url, json=payload, timeout=30)
        if res.status_code == 200:
            return res.json()
        else:
            st.error(f"Lỗi {res.status_code}: {res.text}")
            return None
    except Exception as e:
        st.error(f"❌ Không thể kết nối backend: {e}")
        return None
    
# --- Main UI ---

def call_upload2(file_bytes: bytes, filename: str, folder_name: str):
    # url = f"{st.session_state.api_base}/cv/upload"
    url = api_url("/cv/upload")
    try:
        resp = requests.post(
            url, 
            files={"file": (filename, file_bytes.getvalue(), "application/pdf")}, 
            data={"job_apply": folder_name} ,
            timeout=(10, 600))
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        st.error(f"Upload error: {e}")
        if hasattr(e, 'response') and e.response is not None:
            st.error(f"Response: {e.response.text}")
        raise


# ---------------- Email helper (uses safe_post) ----------------
def call_send_invite(candidate_email, subject, body, interview_time=None):
    # keep hr_email and phone optional and separate from the HTML body
    def _make_payload(hr_email=None, phone=None):
        p = {
            "email": candidate_email,
            "subject": subject,
            "body": body,
            "interview_time": interview_time,
        }
        if hr_email:
            p["hr_email"] = hr_email
        if phone:
            p["phone"] = phone
        return p

    try:
        url = api_url("/invite")
        # default send without hr/phone; caller may include them via kwargs
        res = requests.post(url, json=_make_payload(), timeout=30)
        if res is None:
            return None
        res.raise_for_status()
        return res.json()
    except Exception as e:
        st.error(f"Invite error: {e}")
        return None

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
                resp = call_upload2(fh, file_name, folder_name)  # gọi API
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
    st.title("📄 CV Manager")
    st.markdown("### 🔍 Trạng thái tuyển dụng hiện tại")
    st.markdown("<hr>", unsafe_allow_html=True)

    # CSS
    st.markdown("""
    <style>
    div[data-testid="stHorizontalBlock"] {
        background-color: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        padding: 18px 22px;
        border-radius: 12px;
        margin-bottom: 14px;
        transition: background-color 0.3s, transform 0.2s;
    }
    div[data-testid="stHorizontalBlock"]:hover {
        background-color: rgba(255, 255, 255, 0.08);
        transform: translateY(-2px);
    }
    .job-title {
        font-size: 20px;
        font-weight: 600;
        color: #fafafa;
        margin-bottom: 6px;
    }
    .job-count {
        font-size: 15px;
        color: #cccccc;
        margin-bottom: 0;
    }
    div[data-testid="stButton"] button {
        font-size: 13px !important;
        padding: 4px 10px !important;
        border-radius: 8px !important;
        background-color: rgba(120, 120, 255, 0.15) !important;
        color: #d0cfff !important;
        border: 1px solid rgba(150, 150, 255, 0.3) !important;
        transition: background-color 0.2s, border-color 0.2s;
    }
    div[data-testid="stButton"] button:hover {
        background-color: rgba(150, 150, 255, 0.25) !important;
        border-color: rgba(170, 170, 255, 0.4) !important;
    }
    .uploader-wrapper {
        display: flex;
        justify-content: center;
        align-items: center;
        padding: 10px 0 0 0;
    }
    [data-testid="stFileUploader"] {
        width: 60% !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # API
    url = api_url("/candidate/count")
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        st.error(f"Không thể kết nối API: {e}")
        return

    if not data:
        st.info("Chưa có dữ liệu ứng viên nào.")
        return

    # Hiển thị từng job
    for job, count in data.items():
        with st.container():
            col1, col2, col3 = st.columns([3, 0.8, 0.8])

            # --- Cột 1: thông tin job ---
            with col1:
                if st.button(f"💼 {job}", key=f"view_{job}"):
                    st.session_state["viewing_job"] = job
                # st.markdown(f"<div class='job-title'>💼 {job}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='job-count'>{count} ứng viên</div>", unsafe_allow_html=True)

            # --- Cột 2: thêm CV ---
            with col2:
                if "show_upload" not in st.session_state:
                    st.session_state["show_upload"] = {}

                if st.button("➕ Thêm CV", key=f"toggle_{job}"):
                    st.session_state["show_upload"][job] = not st.session_state["show_upload"].get(job, False)

            # --- Cột 3: xóa job ---
            with col3:
                if st.button("🗑️ Xóa", key=f"delete_{job}"):
                    requests.post(api_url("/job_apply/delete"), data={"job_apply": job})

            # --- Uploader: nằm dưới hàng ---
            if st.session_state["show_upload"].get(job, False):
                st.markdown('<div class="uploader-wrapper">', unsafe_allow_html=True)

                uploaded_file = st.file_uploader(
                    "Chọn file PDF",
                    type=["pdf"],
                    key=f"uploader_{job}",
                    label_visibility="collapsed",
                )

                if uploaded_file:
                    if st.button("📤 Upload", key=f"upload_{job}"):
                        res = requests.post(
                            api_url("/cv/upload"),
                            data={"job_apply": job},
                            files={"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")},
                        )
                        if res.ok:
                            st.success(f"✅ Đã thêm CV vào {job}")
                        else:
                            st.error("❌ Upload thất bại")

                st.markdown('</div>', unsafe_allow_html=True)
            if st.session_state.get("viewing_job") == job:
                st.markdown("---")
                st.markdown(f"#### 📋 Danh sách ứng viên cho {job}")

                try:
                    res = requests.get(api_url(f"/candidate/by_job/{job}"))
                    res.raise_for_status()
                    candidates = res.json()
                except Exception as e:
                    st.error(f"Không thể tải danh sách: {e}")
                    candidates = []

                if candidates:
                    df = pd.DataFrame(candidates)[["name", "email", "public_url"]]
                    df["📎 CV"] = df["public_url"].apply(lambda x: f"<a href=\"{x}\" target=\"_blank\">Xem CV</a>")
                    df = df[["name", "email", "📎 CV"]]

                    # Use HTML rendering to avoid optional pandas dependency 'tabulate'
                    st.markdown(df.to_html(escape=False, index=False), unsafe_allow_html=True)
                else:
                    st.info("Không có ứng viên nào cho vị trí này.")

def upload_with_Drive():
    st.title("📄 Upload CV với Google Drive")

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

    # # top_qs = get_top_questions(3)
    # # if top_qs:
    # #     st.markdown("💡 <b>Gợi ý câu hỏi:</b>", unsafe_allow_html=True)
    # #     cols = st.columns(len(top_qs))
    # #     for i, q_text in enumerate(top_qs):
    # #         if cols[i].button(q_text, key=f"suggest_{i}"):
    # #             st.session_state["selected_question"] = q_text

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
                render_selectable_table(df_scored, key="scored_results_editor")
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

def call_jobs():
    import requests
    try:
        res = requests.get(api_url("/jobs"))
        if res.status_code == 200:
            data = res.json()
            return data.get("jobs", [])
    except Exception as e:
        st.error(f"Lỗi khi tải danh sách công việc: {e}")
    return []

@st.cache_data(ttl=300)
def fetch_suggestions_for_job(job: str):
    if not job or job == "Tất cả":
        return {"schools": [], "skills": []}
    try:
        res = requests.get(api_url("/suggestions"), params={"job": job}, timeout=8)
        if res.ok:
            data = res.json()
            return {
                "schools": data.get("schools", []) if isinstance(data, dict) else [],
                "skills": data.get("skills", []) if isinstance(data, dict) else []
            }
    except Exception as e:
        # Không throw — frontend vẫn hoạt động với danh sách rỗng
        st.warning(f"Không lấy được gợi ý từ backend: {e}")
    return {"schools": [], "skills": []}

def view_search2():
    header()
    st.markdown("<div style='margin-top:0.6rem'></div>", unsafe_allow_html=True)

    st.subheader("🎯 Chọn vị trí tuyển dụng")

    # --- Lấy danh sách job_apply ---
    job_list = call_jobs()
    selected_job = st.selectbox(
        "Vị trí ứng tuyển",
        options=["Tất cả"] + job_list if job_list else ["Tất cả"],
        index=0,
        help="Chọn vị trí mà bạn muốn tìm ứng viên"
    )

    st.markdown("---")
    st.subheader("🔎 Tìm kiếm ứng viên theo tiêu chí")

    # --- Gợi ý filter ---
    suggestions = fetch_suggestions_for_job(selected_job)
    school_options = ["(Không chọn)"] + suggestions.get("schools", [])
    school_options.append("Khác (tự nhập)")
    skill_options = suggestions.get("skills", [])

    # --- Quản lý state ---
    if "custom_skills" not in st.session_state:
        st.session_state["custom_skills"] = []

    # -----------------------
    # PHẦN FORM CHÍNH
    # -----------------------
    with st.form("search_form"):
        col1, col2 = st.columns(2)
        with col1:
            school_choice = st.selectbox("🏫 Trường học", options=school_options, index=0)
            if school_choice == "Khác (tự nhập)":
                school_input = st.text_input("Nhập tên trường", placeholder="VD: Đại học Kinh tế Luật")
                school_value = school_input.strip() if school_input else None
            elif school_choice == "(Không chọn)":
                school_value = None
            else:
                school_value = school_choice

            gpa = st.text_input("📊 Ngưỡng GPA", placeholder="VD: 3.2, 3.5, 4.0")

        with col2:
            combined_skills = list(dict.fromkeys(skill_options + st.session_state["custom_skills"]))
            selected_skills = st.multiselect("💻 Kỹ năng (chọn nhiều)", options=combined_skills)
            english_cert_only = st.checkbox("🎓 Chỉ ứng viên có chứng chỉ ngoại ngữ (IELTS/TOEIC/TOEFL)")

        exp_detail = st.text_area("🧑‍💼 Chi tiết kinh nghiệm", placeholder="VD: Data Analyst tại ABC...")
        project_detail = st.text_area("📁 Chi tiết dự án", placeholder="VD: LLM chatbot, Web app,...")

        run = st.form_submit_button("🔍 Tìm kiếm", type="primary")

    # -----------------------
    # PHẦN THÊM SKILL (ngoài form)
    # -----------------------
    # st.markdown("### ➕ Thêm kỹ năng tuỳ chỉnh")
    # new_skill = st.text_input("Thêm kỹ năng khác", key="new_skill_input", placeholder="VD: FastAPI, GCP, Figma...")

    # if st.button("Thêm skill", key="btn_add_skill"):
    #     ns = new_skill.strip()
    #     if ns and ns not in st.session_state["custom_skills"]:
    #         st.session_state["custom_skills"].append(ns)
    #         st.success(f"✅ Đã thêm kỹ năng: {ns}")
    #     st.session_state["new_skill_input"] = ""

    # Khi submit form -> gửi payload tới backend
    if run:
        # Chuẩn hóa payload: gửi selected_job trừ khi Tất cả
        payload = {
            "job_apply": None if selected_job == "Tất cả" else selected_job,
            "school": school_value,
            "gpa": float(gpa.strip()) if gpa else None,
            "english_cert_only": bool(english_cert_only),
            # Gửi skill dưới dạng list (backend nên chấp nhận list)
            "skills": selected_skills or None,
            "exp_detail": exp_detail.strip() if exp_detail else None,
            "project_detail": project_detail.strip() if project_detail else None,
            
        }
        with st.spinner("Đang xử lý..."):
            data = call_FilterQuery(payload)  # cập nhật hàm call_query để nhận dict thay vì q string
            if not data:
                st.warning("❌ Không có kết quả nào khớp với tiêu chí.")
                return

        # Xử lý kết quả như cũ
        try:
            df = pd.DataFrame(data)
        except Exception as e:
            st.error(f"⚠️ Lỗi khi xử lý dữ liệu: {e}")
            st.json(data)  # in thử dữ liệu ra cho dễ debug
            return

        # Loại trùng email nếu có
        if "email" in df.columns:
            df = df.drop_duplicates(subset=["email"], keep="first")

        # Lưu vào session state để tái sử dụng
        st.session_state["df_original"] = df

        # ✅ Hiển thị kết quả tìm kiếm
        st.success(f"✅ Tìm thấy {len(df)} ứng viên phù hợp")
        
    # show selectable table with Invitation column
    render_selectable_table(df, key="search_results_editor")
        # df_scored = filter_ui_dynamic(df, df.to_dict(orient="records"))
        # col_left, col_right = st.columns([0.28, 0.72])
        # with col_left:
        #     df_scored = filter_ui_dynamic(df, df.to_dict(orient="records"))
        # with col_right:
        #     render_table_view(df_scored)



# ------------ SEND EMAIL ----------------
# def call_send_invite(candidate_email, subject, body, interview_time=None):
#     url = f"{st.session_state.api_base}/invite"
#     payload = {
#         "email": candidate_email,
#         "subject": subject,
#         "body": body,
#         "interview_time": interview_time
#     }
#     try:
#         resp = requests.post(url, json=payload, timeout=30)
#         resp.raise_for_status()
#         return resp.json()
#     except Exception as e:
#         st.error(f"Invite error: {e}")
#         return None

# def invite_model(candidate):
#     with st.form(f"invite_form_{candidate['id']}"):
#         st.markdown(f"""
#         <h3>📩 Interview Invitation for <b>{candidate['full_name']}</b></h3>
#         <hr style="border:1px solid #ddd;">
#         <p>Please review the details below and send the invitation email.</p>
#         """, unsafe_allow_html=True)

#         # Company details
#         company_name = st.text_input("🏢 Company Name", value="ABC Tech Ltd.")
#         hr_email = st.text_input("📧 HR Contact Email", value="hr@abctech.com")
#         phone_number = st.text_input("📞 Contact Phone", value="+84 123 456 789")
#         location = st.text_input("📍 Interview Location", value="123 Nguyen Trai, Hanoi")

#         # Email content (HTML body)
#         subject = st.text_input("✉️ Email Subject", value="Interview Invitation")
#         template = st.text_area(
#             "📝 Email Body (HTML Supported)",
#             value=f"""
# <html>
#   <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
#     <p>Dear <b>{candidate.get('full_name','')}</b>,</p>

#     <p>We are pleased to invite you for an interview for the position of 
#     <b>{candidate.get('job_title','')}</b> at <b>{company_name}</b>.</p>

#     <table style="border-collapse: collapse; margin: 15px 0;">
#       <tr><td style="padding: 6px 12px;">📅 <b>Interview Date:</b></td><td>[Choose below]</td></tr>
#       <tr><td style="padding: 6px 12px;">⏰ <b>Time:</b></td><td>[Choose below]</td></tr>
#       <tr><td style="padding: 6px 12px;">📍 <b>Location:</b></td><td>{location}</td></tr>
#       <tr><td style="padding: 6px 12px;">📞 <b>Contact:</b></td><td>{phone_number}</td></tr>
#       <tr><td style="padding: 6px 12px;">📧 <b>HR Email:</b></td><td>{hr_email}</td></tr>
#     </table>

#     <p>Please confirm your availability at your earliest convenience.</p>

#     <p>Best regards,<br>
#     <b>{company_name} Recruitment Team</b></p>
#   </body>
# </html>
#             """.strip()
#         )

#         # Interview scheduling
#         interview_date = st.date_input("📅 Interview Date")
#         time_slot = st.selectbox("⏰ Time Slot", ["09:00", "10:00", "14:00", "16:00"])

#         submitted = st.form_submit_button("📤 Send Invitation")
#         if submitted:
#             res = call_send_invite(
#                 candidate_email=candidate["email"],
#                 subject=subject,
#                 body=template,
#                 interview_time=f"{interview_date} {time_slot}"
#             )
#             if res:
#                 st.success("✅ Invitation email sent successfully!")
#             else:
#                 st.error("❌ Failed to send email.")


                # --- Khởi tạo session_state cho danh sách ứng viên đã chọn gửi email ---
if "invite_pool" not in st.session_state:
    # map email -> {id, email, full_name, job_title, resume_url}
    st.session_state["invite_pool"] = {}

# --- Helper chuẩn hoá dữ liệu ứng viên ---
def _normalize_candidate(row: dict) -> dict:
    """Chuẩn hoá record ứng viên để lưu trong invite_pool."""
    # Accept multiple possible key variants
    def pick(r, keys):
        for k in keys:
            if k in r and r.get(k):
                return r.get(k)
        return None

    return {
        "id": pick(row, ["id", "Id", "ID"]),
        "email": pick(row, ["email", "Email", "e-mail"]),
        "full_name": pick(row, ["full_name", "fullName", "name", "Name", "full name", "Full name"]),
        "job_title": pick(row, ["job_title", "jobTitle", "Job Title", "Job title"]),
        "resume_url": pick(row, ["resume_url", "public_url", "file_url", "resumeUrl"]),
        "educations": pick(row, ["educations", "education", "educs"])
    }

# --- Hàm render bảng kết quả có cột Invitation ---
def render_selectable_table(df: pd.DataFrame, key: str = "candidates_editor"):
    """Render a selectable table using per-row checkboxes (more stable than data_editor).
    Updates st.session_state['invite_pool'] keyed by email.
    """
    if df is None or df.empty:
        st.info("Không có dữ liệu để hiển thị.")
        return

    # Ensure invite_pool exists
    if "invite_pool" not in st.session_state:
        st.session_state["invite_pool"] = {}

    # Show header with counts
    st.markdown(f"**🔎 Hiển thị {len(df)} ứng viên**")

    # Render rows
    for idx, row in df.reset_index(drop=True).iterrows():
        # normalize
        r = _normalize_candidate(row.to_dict())
        email = r.get("email") or f"row_{idx}"

        c1, c2, c3, c4, c5 = st.columns([3, 4, 3, 3, 0.6])
        with c1:
            st.markdown(f"**{html.escape(str(r.get('full_name') or '—'))}**")
            st.caption(r.get("job_title") or "—")
        with c2:
            if r.get("email"):
                st.markdown(f"[{r.get('email')}]({ 'mailto:' + r.get('email') })")
            else:
                st.write("—")
        with c3:
            edu_html = education_to_chips(r.get("educations") or row.get("educations") or [])
            if edu_html:
                st.markdown(edu_html, unsafe_allow_html=True)
            else:
                st.write("—")
        with c4:
            resume = r.get("resume_url")
            if resume:
                st.markdown(f"[🔗 CV]({resume})")
            else:
                st.write("—")
        # checkbox column
        checked = email in st.session_state["invite_pool"]
        cb_key = f"invite_checkbox_{email}_{idx}"
        checked_now = st.checkbox("", value=checked, key=cb_key)

        # update pool
        if checked_now and email not in st.session_state["invite_pool"]:
            st.session_state["invite_pool"][email] = r
        if (not checked_now) and email in st.session_state["invite_pool"]:
            # only remove if this email corresponds to this row (avoid removing others accidentally)
            st.session_state["invite_pool"].pop(email, None)

    # small footer
    st.markdown(f"\n---\n🔖 Đã chọn: **{len(st.session_state['invite_pool'])}** ứng viên để mời.")

# --- Tab "✉️ Invite" ---
def view_invite_tab():
    header()
    invited = list(st.session_state["invite_pool"].values())
    st.subheader(f"📩 Danh sách đã chọn mời phỏng vấn: {len(invited)}")

    if not invited:
        st.info("Chưa chọn ứng viên nào. Hãy vào tab **Search** hoặc **Filter Search** và tick cột **Invitation**.")
        return

    # Bảng danh sách + nút xoá từng người
    for cand in invited:
        c1, c2, c3, c4 = st.columns([3, 3, 3, 1])
        with c1:
            st.write(f"**{cand.get('full_name') or '(No name)'}**")
            st.caption(cand.get("job_title") or "—")
        with c2:
            st.write(cand.get("email"))
        with c3:
            url = cand.get("resume_url")
            if url:
                st.markdown(f"[🔗 CV]({url})")
            else:
                st.write("—")
        with c4:
            if st.button("🗑️", key=f"rm_{cand['email']}"):
                st.session_state["invite_pool"].pop(cand["email"], None)
                st.rerun()

    st.divider()

    # Form gửi hàng loạt
    with st.form("batch_invite_form"):
        st.subheader("✉️ Soạn thư mời (gửi cho tất cả đã chọn)")
        colA, colB = st.columns(2)
        with colA:
            company_name = st.text_input("🏢 Company", value="Your Company")
            location     = st.text_input("📍 Địa điểm", value="Online / Văn phòng")
        with colB:
            phone_number = st.text_input("📞 SĐT liên hệ", value="+84 ...")
            hr_email     = st.text_input("📧 HR Email", value="hr@example.com")

        subject = st.text_input("Tiêu đề", value="Interview Invitation")
        interview_date = st.date_input("Ngày phỏng vấn")
        time_slot = st.selectbox("Khung giờ", ["09:00", "10:00", "14:00", "16:00"])

        default_body = f"""
<html>
  <body style="font-family: Arial, sans-serif; line-height:1.6; color:#333;">
    <p>Dear <b>{{name}}</b>,</p>
    <p>We would like to invite you to interview for the position of <b>{{job_title}}</b> at <b>{company_name}</b>.</p>
    <ul>
      <li><b>Date</b>: {interview_date} </li>
      <li><b>Time</b>: {time_slot}</li>
      <li><b>Location</b>: {location}</li>
      <li><b>Contact</b>: {phone_number} — {hr_email}</li>
    </ul>
    <p>Please reply to confirm your availability.</p>
    <p>Best regards,<br><b>{company_name}</b> Recruitment Team</p>
  </body>
</html>
""".strip()
        body = st.text_area("Nội dung (HTML được hỗ trợ) — dùng {{name}} và {{job_title}} để cá nhân hoá",
                            value=default_body, height=240)

        colX, colY, colZ = st.columns([1,1,1])
        with colX:
            send_all = st.form_submit_button("📤 Gửi tất cả", type="primary")
        with colY:
            export = st.form_submit_button("⬇️ Export emails (CSV)")
        with colZ:
            clear_all = st.form_submit_button("🧹 Xoá toàn bộ danh sách")

    # Hành động
    if send_all:
        ok, fail = 0, 0
        for cand in invited:
            personalized = (body
                            .replace("{{name}}", cand.get("full_name") or "")
                            .replace("{{job_title}}", cand.get("job_title") or ""))
            try:
                res = call_send_invite(cand["email"], subject, personalized, interview_time=f"{interview_date} {time_slot}")
                if res:
                    ok += 1
                else:
                    fail += 1
            except Exception:
                fail += 1
        if ok:
            st.success(f"Đã gửi thành công {ok}/{len(invited)} thư mời.")
        if fail:
            st.warning(f"Gửi thất bại {fail} ứng viên. Kiểm tra backend / cấu hình email.")

    if export:
        csv_bytes = pd.DataFrame(invited)[["full_name", "email", "job_title"]].to_csv(index=False).encode("utf-8")
        st.download_button("Download invites.csv", data=csv_bytes, file_name="invites.csv", mime="text/csv")

    if clear_all:
        st.session_state["invite_pool"].clear()
        st.toast("Đã xoá toàn bộ danh sách mời.", icon="🧹")
        st.rerun()


# ---------------- Router ----------------
with st.sidebar:
    pass

if "📤" in st.session_state.get("nav", ""):
    pass  # not used; we rely on 'nav' variable below

if __name__ == "__main__" or True:

    if nav == "✉️ Main":
        view_main()
    elif nav == "🗂️ Drive Upload":
        upload_with_Drive()
    elif nav == "🔎 Search":
        view_search()
    elif nav == "🔽 Filter Search":
        view_search2()
    elif nav == "✉️ Invite":
        view_invite_tab()

# streamlit run main.py