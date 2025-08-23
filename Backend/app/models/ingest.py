# ingest.py — ingest JSON CV vào schema lean
from __future__ import annotations
from datetime import date
import re
import sys
from typing import Optional, Tuple

import dateparser
from sqlalchemy.orm import Session

from models import (
    get_engine, create_all, SessionLocal,
    Candidate, Education, Experience,
    Skill, Language, candidate_skills, candidate_languages
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


# ---------- main upsert ----------
def upsert_candidate_from_json(db: Session, cv: dict) -> Candidate:
    cand = find_or_create_candidate(db, cv)

    # core fields
    cand.full_name = cv.get("full_name")
    cand.email     = cv.get("email")
    cand.phone     = cv.get("phone")
    cand.job_title = cv.get("job_title")
    cand.location  = cv.get("location")

    db.flush()

    # --- Education (replace all) ---
    cand.education.clear()
    for e in cv.get("education", []):
        edu = Education(
            candidate_id=cand.id,
            degree=e.get("degree"),
            university=e.get("university"),
            start_year=e.get("start_year") if isinstance(e.get("start_year"), int) else None,
            end_year=e.get("end_year") if isinstance(e.get("end_year"), int) else None,
        )
        cand.education.append(edu)

    # --- Experience (replace all) ---
    cand.experience.clear()
    for xp in cv.get("experience", []):
        sd, s_cur = normalize_date(xp.get("start_date"))
        ed, e_cur = normalize_date(xp.get("end_date"))
        ex = Experience(
            candidate_id=cand.id,
            company=xp.get("company"),
            job_title=xp.get("job_title"),
            start_date=sd,
            end_date=ed,
            is_current=bool(s_cur or e_cur),
            description=xp.get("description"),
        )
        cand.experience.append(ex)

    # --- Skills (merge) ---
    # Lấy set skill_id hiện có để tránh trùng
    existing_skill_ids = {
        r[0] for r in db.execute(
            candidate_skills.select().where(candidate_skills.c.candidate_id == cand.id)
        )
    }
    for name in cv.get("skills", []):
        try:
            s = get_or_create_skill(db, name)
        except ValueError:
            continue
        if s.id not in existing_skill_ids:
            db.execute(candidate_skills.insert().values(candidate_id=cand.id, skill_id=s.id))
            existing_skill_ids.add(s.id)

    # --- Languages (merge) ---
    existing_lang_ids = {
        r[0] for r in db.execute(
            candidate_languages.select().where(candidate_languages.c.candidate_id == cand.id)
        )
    }
    for name in cv.get("languages", []):
        try:
            l = get_or_create_language(db, name)
        except ValueError:
            continue
        if l.id not in existing_lang_ids:
            db.execute(candidate_languages.insert().values(candidate_id=cand.id, language_id=l.id))
            existing_lang_ids.add(l.id)

    db.flush()
    return cand


# ---------- CLI demo ----------
SAMPLE = {
    "full_name": "JR Sabado",
    "email": "sabadotweetie@gmail.com",
    "phone": "+639 17887 1043",
    "job_title": "Software Engineer",
    "location": None,
    "education": [
        {"degree": "B.Sc. Information Systems", "university": "University of Santo Tomas", "start_year": None, "end_year": 2014}
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
    cand = upsert_candidate_from_json(db, cv)
    db.commit()
    return cand


def main(db_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/scan_cv"):
    engine = create_all(db_url)
    SessionLocal.configure(bind=engine)

    with SessionLocal() as db:
        cand = insert_candidate_to_db(db, SAMPLE)
        print(f"Upserted candidate id={cand.id} email={cand.email}")


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "postgresql+psycopg2://postgres:postgres@localhost:5432/scan_cv"
    main(url)
