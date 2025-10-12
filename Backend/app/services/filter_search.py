from sqlalchemy import text as sa_text
from sqlalchemy import or_
from app.models.models import Candidate, Educations, candidate_skills, Skill, candidate_languages, Language, Certification


def search_filter_sql(job_apply, school, gpa, english_cert_only, skills, db):
    query = db.query(Candidate)

    # --- 1️⃣ Lọc theo vị trí ứng tuyển ---
    if job_apply:
        query = query.filter(Candidate.job_apply == job_apply)

    # --- 2️⃣ Lọc theo trường học & GPA ---
    if school or gpa is not None:
        query = query.join(Educations, Candidate.id == Educations.candidate_id)
        if school:
            query = query.filter(Educations.university.ilike(f"%{school}%"))
        if gpa is not None:
            query = query.filter(Educations.gpa >= gpa)

    # --- 3️⃣ Lọc theo kỹ năng ---
    if skills:
        query = (
            query.join(candidate_skills, Candidate.id == candidate_skills.c.candidate_id)
                 .join(Skill, Skill.id == candidate_skills.c.skill_id)
                 .filter(Skill.name.in_(skills))
        ).distinct()

    # --- 4️⃣ Lọc theo chứng chỉ tiếng Anh ---
    if english_cert_only:
        english_keywords = ["ielts", "toeic", "toefl"]
        query = query.join(Certification, Candidate.id == Certification.candidate_id)
        query = query.filter(
            or_(
                *[Certification.certificate_name.ilike(f"%{kw}%") for kw in english_keywords]
            )
        )

    # --- Kết quả ---
    results = query.distinct().all()
    return [
        {
           "id": c.id,
            "full_name": c.full_name,
            "email": c.email
        }
        for c in results
    ]

