
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List, Dict, Tuple, Any, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy import inspect as sa_inspect

# =========================
# 1) SELECTOR (rule-based)
# =========================
SKILL_WORDS = r"(kỹ năng|skill|skills|tech|framework|ngôn ngữ lập trình|biết|thành thạo)"
EXP_WORDS   = r"(kinh nghiệm|từng làm|đã làm|làm việc|company|công ty|experience|worked)"
EDU_WORDS = r"(bằng cấp|đại học|university|degree|gpa|điểm trung bình|học|tốt nghiệp|education|studied|field of study)"
LOC_WORDS   = r"(địa điểm|location|ở|tại|HCM|HCMC|Ho Chi Minh|Hà Nội|Hanoi|Huế|Đà Nẵng|Singapore|USA|UK)"
LANG_WORDS  = r"(ngôn ngữ|language|languages|tiếng anh|tiếng nhật|english|japanese|vietnamese)"
CERT_WORDS  = r"(chứng chỉ|certificate|chứng nhận)"
def selector_lite(user_query: str) -> Tuple[List[str], str]:
    """
    Trả về (danh_sách_bảng_cần, hints chuỗi) dựa theo từ khóa.
    """
    uq = user_query.lower()
    tables = {"candidates"}  # mặc định luôn cần ứng viên

    hints = []

    if re.search(SKILL_WORDS, uq):
        tables |= {"skills", "candidate_skills"}
        hints.append("This query involves candidate skills; join skills via candidate_skills.")
        hints.append("If returning a candidate list, use DISTINCT or EXISTS to avoid duplicates.")

    if re.search(EXP_WORDS, uq):
        tables |= {"experiences"}
        hints.append("This query involves work experiences; join experiences on candidate_id.")

    if re.search(EDU_WORDS, uq):
        tables |= {"educations"}
        hints.append("This query involves education; join education on candidate_id.")

    if re.search(LANG_WORDS, uq):
        tables |= {"languages", "candidate_languages"}
        hints.append("This query involves languages; join languages via candidate_languages.")
        hints.append("For unique candidates, use DISTINCT or EXISTS when combining many-to-many joins.")

    if re.search(CERT_WORDS, uq):
        tables |= {"certifications"}
        hints.append("This query involves certifications.")
        hints.append("For unique candidates, use DISTINCT or EXISTS when combining many-to-many joins.")

    if re.search(LOC_WORDS, uq):
        hints.append("User mentions location; consider filtering candidates.location with ILIKE.")

    if not hints:
        hints.append("If unsure, start from candidates and add joins only if needed.")

    return sorted(tables), " ".join(hints)