# candidate_schema.py
from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field

# ------------ Education ------------
class Education(BaseModel):
    degree: Optional[str] = None
    university: Optional[str] = None
    start_year: Optional[int] = None
    end_year: Optional[int] = None

    class Config:
        orm_mode = True  # Pydantic v1
        # Pydantic v2: from_attributes = True

# ------------ Experience (In/Out tách kiểu ngày) ------------
class ExperienceIn(BaseModel):
    job_title: Optional[str] = None
    company: Optional[str] = None
    start_date: Optional[str] = None   # raw string: "Aug 2017", "Present", ...
    end_date: Optional[str] = None     # raw string
    description: Optional[str] = None

class ExperienceOut(BaseModel):
    id: int
    job_title: Optional[str] = None
    company: Optional[str] = None
    start_date: Optional[date] = None  # đã parse & lưu DB
    end_date: Optional[date] = None
    is_current: Optional[bool] = None
    description: Optional[str] = None

    class Config:
        orm_mode = True
        # Pydantic v2: from_attributes = True

# ------------ Certification ------------
class Certification(BaseModel):
    certificate_name: Optional[str] = None
    organization: Optional[str] = None

    class Config:
        orm_mode = True

# ------------ Attachment ------------
class Attachment(BaseModel):
    type: Optional[str] = None  # 'pdf', 'docx'

    class Config:
        orm_mode = True

# ------------ Candidate (In/Out) ------------
class CandidateIn(BaseModel):
    full_name: Optional[str] = None
    job_title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None

    education: List[Education] = Field(default_factory=list)
    experience: List[ExperienceIn] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    certifications: List[Certification] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    attachments: List[Attachment] = Field(default_factory=list)

class CandidateOut(BaseModel):
    id: int
    full_name: Optional[str] = None
    job_title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None

    education: List[Education] = Field(default_factory=list)
    experience: List[ExperienceOut] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)          # nếu muốn trả tên skill đơn giản
    languages: List[str] = Field(default_factory=list)       # tương tự
    certifications: List[Certification] = Field(default_factory=list)
    attachments: List[Attachment] = Field(default_factory=list)

    class Config:
        orm_mode = True
        # Pydantic v2: from_attributes = True
