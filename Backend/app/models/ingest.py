# ingest.py — ingest JSON CV vào schema lean (UPD: idempotent m2m)
from __future__ import annotations
from datetime import date
import re
import sys
from typing import Any, Dict, Optional, Tuple, List

import fitz
import dateparser
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.models import (
    get_engine, create_all, SessionLocal,
    Candidate, Educations, Experience,
    Skill, Language, candidate_skills, candidate_languages,
    Certification, Attachment
)

CVS_PATH = "../../raw/cvs"

# ---------- helpers ----------
def normalize_date(s: Optional[str]) -> Tuple[Optional[date], bool]:
    """
    Trả về (ngày chuẩn hoá hoặc None, is_current).
    - 'Present/Current/Now' -> (None, True)
    - 'Aug 2017'            -> (2017-08-01, False)
    - '2014'                -> (2014-01-01, False)
    - None/parse fail       -> (None, False)
    """
    if not s:
        return None, False
    s_norm = s.strip().lower()
    if s_norm in {"present", "current", "now"}:
        return None, True

    # năm thuần tuý
    if re.fullmatch(r"\d{4}", s_norm):
        y = int(s_norm)
        return date(y, 1, 1), False

    dt = dateparser.parse(
        s,
        settings={
            "PREFER_DAY_OF_MONTH": "first",
            "PREFER_DATES_FROM": "past",
            "DATE_ORDER": "MDY",  # đổi 'DMY' nếu CV chủ yếu định dạng ngày VN
        },
    )
    if not dt:
        return None, False
    # chốt mùng 1 để đồng nhất khi chỉ có tháng-năm
    return date(dt.year, dt.month, 1), False


def get_or_create_skill(db: Session, name: str) -> Skill:
    norm = name.strip()
    if not norm:
        raise ValueError("Empty skill name")
    s = db.query(Skill).filter(Skill.name.ilike(norm)).one_or_none()
    if s:
        return s
    s = Skill(name=norm)
    db.add(s)
    db.flush()
    return s


def get_or_create_language(db: Session, name: str) -> Language:
    norm = name.strip()
    if not norm:
        raise ValueError("Empty language name")
    l = db.query(Language).filter(Language.name.ilike(norm)).one_or_none()
    if l:
        return l
    l = Language(name=norm)
    db.add(l)
    db.flush()
    return l


def find_or_create_candidate(db: Session, payload: dict) -> Candidate:
    email = payload.get("email")
    cand = None
    if email:
        cand = db.query(Candidate).filter(Candidate.email == email).one_or_none()
    if not cand:
        # fallback: match lỏng theo (full_name, phone)
        cand = db.query(Candidate).filter(
            Candidate.full_name == payload.get("full_name"),
            Candidate.phone == payload.get("phone"),
        ).one_or_none()
    if not cand:
        cand = Candidate()
        db.add(cand)
        db.flush()
    return cand


# --------- small utils (robust typing/clean) ---------
def _as_list(x: Any) -> List[Any]:
    """Đảm bảo luôn trả về list (None/str/dict -> list hợp lệ)."""
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, (str, dict)):
        return [x]
    return []

def _clean_str(x: Any) -> Optional[str]:
    """Chuẩn hoá chuỗi: strip, rỗng -> None."""
    if x is None:
        return None
    if not isinstance(x, str):
        x = str(x)
    x = x.strip()
    return x or None

def _uniq_norm_list(strings: Optional[List[Any]]) -> List[str]:
    """Khử trùng theo casefold để tránh lỗi lặp (e.g., 'JavaScript' vs 'javascript')."""
    out, seen = [], set()
    for s in strings or []:
        if s is None:
            continue
        s2 = _clean_str(s)
        if not s2:
            continue
        key = s2.casefold()
        if key not in seen:
            seen.add(key)
            out.append(s2)
    return out

# --------- idempotent link helpers (ON CONFLICT DO NOTHING) ---------
def link_skill(db: Session, candidate_id: int, skill_id: int) -> None:
    stmt = (
        pg_insert(candidate_skills)
        .values(candidate_id=candidate_id, skill_id=skill_id)
        .on_conflict_do_nothing(constraint="uq_candidate_skill")
    )
    db.execute(stmt)

def link_language(db: Session, candidate_id: int, language_id: int) -> None:
    stmt = (
        pg_insert(candidate_languages)
        .values(candidate_id=candidate_id, language_id=language_id)
        .on_conflict_do_nothing(constraint="uq_candidate_language")
    )
    db.execute(stmt)


def parse_gpa_to_4(val) -> float | None:
    """
    Chuẩn hoá GPA về thang 4.0
    - '3.4'       -> 3.4
    - '3.3/4.0'   -> (3.3/4.0)*4 = 3.3
    - '7/10'      -> (7/10)*4 = 2.8
    - '85/100'    -> (85/100)*4 = 3.4
    - 8.0         -> (8/10)*4 = 3.2
    - 92          -> (92/100)*4 = 3.68
    """
    if val is None:
        return None

    # Nếu đã là float hoặc int
    if isinstance(val, (float, int)):
        x = float(val)
        if x <= 4.0:       # đã ở thang 4
            return x
        elif x <= 10.0:    # thang 10
            return round((x / 10) * 4, 2)
        elif x <= 100.0:   # thang 100
            return round((x / 100) * 4, 2)
        else:
            return None

    # Nếu là string
    if isinstance(val, str):
        # Bóc tách tất cả số
        matches = re.findall(r"\d*\.?\d+", val.replace(",", "."))
        if matches:
            try:
                if len(matches) == 2:  # dạng x/y
                    x, y = map(float, matches)
                    if y > 0:
                        return round((x / y) * 4, 2)
                else:  # chỉ có 1 số
                    x = float(matches[0])
                    if x <= 4.0:
                        return x
                    elif x <= 10.0:
                        return round((x / 10) * 4, 2)
                    elif x <= 100.0:
                        return round((x / 100) * 4, 2)
            except ValueError:
                return None
    return None

def handle_cert_score(raw_score: str | None) -> float | None:
    if raw_score is None:
        return None

    s = str(raw_score).strip().lower()

    # Nếu có dạng "550/990" → lấy phần trước "/"
    if "/" in s:
        try:
            return float(s.split("/")[0].strip())
        except:
            return None

    # Nếu có chữ (toeic, ielts...) thì lọc số ra
    match = re.search(r"(\d+(\.\d+)?)", s)
    if match:
        try:
            return float(match.group(1))
        except:
            return None

    # fallback
    try:
        return float(s)
    except:
        return None
    
regex_mapping = {
    r"(Foreign Trade University|FTU|FTU2)": "Đại học Ngoại thương",
    r"(University of Economics Ho Chi Minh City|UEH)": "Đại học Kinh tế TP.HCM",
    r"(University of Economics and Law|UEL)": "Đại học Kinh tế - Luật - ĐHQG TP.HCM",
    r"(University of Finance and Marketing|UFM)": "Đại học Tài chính - Marketing",
    r"(University of Technology and Education|UTE)": "Đại học Sư phạm Kỹ thuật TP.HCM",
    r"(Ho Chi Minh City University of Technology|HUTECH)": "Đại học HUTECH",
    r"(Bach Khoa University|BKU)": "Đại học Bách khoa - ĐHQG TP.HCM",
    r"(Ho Chi Minh City University of Science|HCMUS)": "Đại học Khoa học Tự nhiên - ĐHQG TP.HCM", 
    r"(Ho Chi Minh City University of Social Sciences and Humanities|HCMUSSH)": "Đại học Khoa học Xã hội và Nhân văn - ĐHQG TP.HCM",
    r"(University of Transport and Communications|UTC)": "Đại học Giao thông Vận tải TP.HCM",
    r"(Ho Chi Minh City University of Foreign Languages & IT|HUFLIT)": "Đại học Ngoại ngữ - Tin học TP.HCM",
    r"(Ton Duc Thang University|TDTU)": "Đại học Tôn Đức Thắng",
    r"(Industrial University|IUH)": "Đại học Công nghiệp TP.HCM",
    r"(Saigon Technology University|STU)": "Đại học Công nghệ Sài Gòn",
    r"(University of Information Technology|UIT|VNU-HCM.*Information Technology)": "Đại học Công nghệ thông tin - ĐHQG TP.HCM",
    r"(University of Industry and Trade)": "Đại học Công nghiệp Thương mại TP.HCM",
    r"(Open University|OU)": "Đại học Mở TP.HCM",
    r"(RMIT University|RMIT)": "Đại học RMIT Việt Nam",
    r"(International University|HCMIU)": "Đại học Quốc tế - ĐHQG TP.HCM",
    r"(Sai Gon University|SGU)": "Đại học Sài Gòn",
    r"(Van Lang University|VLU)": "Đại học Văn Lang",
    r"(Hoa Sen University|HSU)": "Đại học Hoa Sen",
    r"(FPT University|FPT)": "Đại học FPT",
    r"(Ho Chi Minh City University of Law|HCMUL)": "Đại học Luật TP.HCM",
    r"(Nguyen Tat Thanh University|NTTU)": "Đại học Nguyễn Tất Thành",
    r"(Ho Chi Minh City University of Architecture|HCMUA)": "Đại học Kiến trúc TP.HCM",
    r"(Ho Chi Minh City University of Economics and Finance|UEF)": "Đại học Kinh tế Tài chính TP.HCM",
    r"(Ho Chi Minh City University of Education|HCMUE)": "Đại học Sư phạm TP.HCM",
}

# Hàm chuẩn hoá
def normalize_university(name):
    for pattern, unified in regex_mapping.items():
        if re.search(pattern, name, flags=re.IGNORECASE):
            return unified
    return name 

# ---------- main upsert ----------
def upsert_candidate_from_json(db: Session, cv: Dict[str, Any]) -> Candidate:
    """
    Nhận dict JSON từ extract_info(text, llm).
    - Chịu lỗi mềm với field thiếu/sai kiểu.
    - Đúng tên quan hệ: cand.educations, cand.experience, cand.certifications.
    - Merge many-to-many (skills, languages) idempotent bằng ON CONFLICT DO NOTHING.
    """
    cand = find_or_create_candidate(db, cv)

    # -------- core fields --------
    cand.full_name = _clean_str(cv.get("full_name"))
    cand.email     = _clean_str(cv.get("email"))
    cand.phone     = _clean_str(cv.get("phone"))
    cand.job_apply =  _clean_str(cv.get("job_apply"))
    cand.job_title = _clean_str(cv.get("job_title"))
    cand.location  = _clean_str(cv.get("location"))
    db.flush()

    # -------- education (replace-all) --------
    edu_list = _as_list(cv.get("education"))
    cand.educations.clear()
    for e in edu_list:
        if not isinstance(e, dict):
            continue
        raw_uni = _clean_str(e.get("university"))
        normalized_uni = normalize_university(raw_uni) if raw_uni else None
        edu = Educations(
            candidate_id = cand.id,
            degree       = _clean_str(e.get("degree")),
            university   = normalized_uni,
            gpa          = parse_gpa_to_4(e.get("gpa")),
            start_year   = e.get("start_year") if isinstance(e.get("start_year"), int) else None,
            end_year     = e.get("end_year")   if isinstance(e.get("end_year"), int)   else None,
        )
        cand.educations.append(edu)

    # -------- experience (replace-all) --------
    exp_list = _as_list(cv.get("experience"))
    cand.experience.clear()  # tên quan hệ là 'experience' (số ít) theo models.py
    for xp in exp_list:
        if not isinstance(xp, dict):
            continue
        sd, s_cur = normalize_date(_clean_str(xp.get("start_date")))
        ed, e_cur = normalize_date(_clean_str(xp.get("end_date")))
        ex = Experience(
            candidate_id = cand.id,
            job_title    = _clean_str(xp.get("job_title")),
            company      = _clean_str(xp.get("company")),
            start_date   = sd,
            end_date     = ed,
            is_current   = bool(s_cur or e_cur),
            description  = _clean_str(xp.get("description")),
        )
        cand.experience.append(ex)

    # -------- certifications (replace-all) --------
    cert_list = _as_list(cv.get("certifications"))
    cand.certifications.clear()
    for c in cert_list:
        if not isinstance(c, dict):
            continue
        cert = Certification(
            candidate_id     = cand.id,
            certificate_name = _clean_str(c.get("certificate_name")),
            organization     = _clean_str(c.get("organization")),
            score = handle_cert_score(c.get("score")),
        )
        cand.certifications.append(cert)

    # -------- skills (idempotent merge) --------
    skills_list = _uniq_norm_list(_as_list(cv.get("skills")))
    for name in skills_list:
        try:
            s = get_or_create_skill(db, name)
            link_skill(db, cand.id, s.id)  # ON CONFLICT DO NOTHING
        except Exception:
            continue

    # -------- languages (idempotent merge) --------
    lang_list = _uniq_norm_list(_as_list(cv.get("languages")))
    for name in lang_list:
        try:
            l = get_or_create_language(db, name)
            link_language(db, cand.id, l.id)  # ON CONFLICT DO NOTHING
        except Exception:
            continue

    db.flush()
    return cand

from sqlalchemy import distinct
def get_unique_job_titles(db):
    result = db.query(distinct(Candidate.job_apply)).all()
    # SQLAlchemy trả list các tuple [(“Data Analyst”,), (“Backend Developer”,)...]
    return [r[0] for r in result if r[0] is not None]


# ---------- CLI demo ----------
SAMPLE = {
    "full_name": "JR Sabado",
    "email": "sabadotweetie@gmail.com",
    "phone": "+639 17887 1043",
    "job_title": "Software Engineer",
    "location": None,
    "education": [
        {
            "degree": "B.Sc. Information Systems",
            "university": "University of Santo Tomas",
            "start_year": None,
            "end_year": 2014
        }
    ],
    "experience": [
        {"job_title": "Software Engineer", "company": "Infor, PSSC, Inc.", "start_date": "Sep 2019", "end_date": "Present",
         "description": "Maintained Homepages, developed Widgets App, H5A migration to Angular..."},
        {"job_title": "Application Development Analyst", "company": "Accenture, Inc.", "start_date": "Aug 2017", "end_date": "Aug 2019",
         "description": "Frontend tasks AngularJS/HTML/CSS, performance improvement, agenda builder..."},
        {"job_title": "R&D PHP Developer", "company": "Gameloft Philippines", "start_date": "Aug 2016", "end_date": "May 2017",
         "description": "CodeIgniter apps, prototypes, infra revamp; projects: Disney MK, Iron Blade..."},
        {"job_title": "Software Development Engineer", "company": "Allied Telesis Labs, Inc.", "start_date": "Aug 2014", "end_date": "Apr 2016",
         "description": "Java GUI applets maintenance; NGFW UI with MEAN; internal systems..."},
        {"job_title": "Web Developer Intern", "company": "Granton World Philippines", "start_date": "Aug 2012", "end_date": "Nov 2013",
         "description": None},
    ],
    "skills": ["Javascript","Typescript","PHP","Java","NodeJS","Angular","HTML","CSS","Git","Azure Devops"],
    "languages": []
}

def insert_candidate_to_db(db: Session, cv: dict) -> Candidate:
    try:
        cand = upsert_candidate_from_json(db, cv)
        db.commit()
        return cand
    except Exception:
        db.rollback()
        raise

def main(db_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/scan_cv"):
    engine = create_all(db_url)
    SessionLocal.configure(bind=engine)
    with SessionLocal() as db:
        cand = insert_candidate_to_db(db, SAMPLE)
        print(f"Upserted candidate id={cand.id} email={cand.email}")

if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "postgresql+psycopg2://postgres:postgres@localhost:5432/scan_cv"
    main(url)
