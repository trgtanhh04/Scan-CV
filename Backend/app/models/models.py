# models.py — lean schema for Text2SQL
from sqlalchemy import (
    Column, Integer, String, ForeignKey, Date, Text,
    Table, UniqueConstraint, Index, DateTime, func, create_engine
)
from sqlalchemy.orm import relationship, declarative_base, sessionmaker
from sqlalchemy.types import Boolean

# ---------------- Base / Engine helpers ----------------
Base = declarative_base()

def get_engine(url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/scan_cv"):
    return create_engine(url, future=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, future=True)

# ---------------- Association tables (many-to-many) ----------------
candidate_skills = Table(
    "candidate_skills",
    Base.metadata,
    Column("candidate_id", Integer, ForeignKey("candidates.id", ondelete="CASCADE"), primary_key=True),
    Column("skill_id",     Integer, ForeignKey("skills.id",      ondelete="CASCADE"), primary_key=True),
    UniqueConstraint("candidate_id", "skill_id", name="uq_candidate_skill"),
)

candidate_languages = Table(
    "candidate_languages",
    Base.metadata,
    Column("candidate_id", Integer, ForeignKey("candidates.id", ondelete="CASCADE"), primary_key=True),
    Column("language_id",  Integer, ForeignKey("languages.id",  ondelete="CASCADE"), primary_key=True),
    UniqueConstraint("candidate_id", "language_id", name="uq_candidate_language"),
)

# ---------------- Core tables ----------------
class Skill(Base):
    __tablename__ = "skills"
    id   = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)   # ví dụ: "Node.js"

    candidates = relationship("Candidate", secondary=candidate_skills, back_populates="skills")

    def __repr__(self) -> str:
        return f"<Skill id={self.id} name={self.name!r}>"

class Language(Base):
    __tablename__ = "languages"
    id   = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)   # ví dụ: "English"

    candidates = relationship("Candidate", secondary=candidate_languages, back_populates="languages")

    def __repr__(self) -> str:
        return f"<Language id={self.id} name={self.name!r}>"


class Candidate(Base):
    __tablename__ = "candidates"

    id         = Column(Integer, primary_key=True, index=True)
    full_name  = Column(String, nullable=True)
    email      = Column(String, unique=True, nullable=True)
    phone      = Column(String, nullable=True)
    job_title  = Column(String, nullable=True)
    location   = Column(String, nullable=True)

    # relations
    educations     = relationship("Educations", back_populates="candidate", cascade="all, delete-orphan")
    experience    = relationship("Experience", back_populates="candidate", cascade="all, delete-orphan")
    certifications= relationship("Certification", back_populates="candidate", cascade="all, delete-orphan")
    attachments   = relationship("Attachment", back_populates="candidate", cascade="all, delete-orphan")

    skills    = relationship("Skill",    secondary=candidate_skills,    back_populates="candidates")
    languages = relationship("Language", secondary=candidate_languages, back_populates="candidates")

    def __repr__(self) -> str:
        return f"<Candidate id={self.id} name={self.full_name!r} email={self.email!r}>"

# Index gợi ý cho các truy vấn phổ biến
Index("idx_candidates_location", Candidate.location)
Index("idx_candidates_job_title", Candidate.job_title)


class Educations(Base):
    __tablename__ = "educations"

    id           = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    degree       = Column(String, nullable=True)
    university   = Column(String, nullable=True)
    start_year   = Column(Integer, nullable=True)   # giữ dạng năm cho đơn giản
    end_year     = Column(Integer, nullable=True)

    candidate    = relationship("Candidate", back_populates="educations")

    def __repr__(self) -> str:
        return f"<Educations id={self.id} candidate_id={self.candidate_id} degree={self.degree!r}>"

class Experience(Base):
    __tablename__ = "experiences"

    id           = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    job_title    = Column(String, nullable=True)
    company      = Column(String, nullable=True)
    start_date   = Column(Date,   nullable=True)    # chuẩn hoá ở bước ingest
    end_date     = Column(Date,   nullable=True)
    is_current   = Column(Boolean, nullable=True)   # True nếu “Present”
    description  = Column(Text,   nullable=True)

    candidate    = relationship("Candidate", back_populates="experience")

    def __repr__(self) -> str:
        return f"<Experience id={self.id} cand={self.candidate_id} {self.company!r} {self.job_title!r}>"

# Index giúp lọc theo thời gian/ứng viên
Index("idx_experiences_candidate_start", Experience.candidate_id, Experience.start_date)

class Certification(Base):
    __tablename__ = "certifications"

    id             = Column(Integer, primary_key=True, index=True)
    candidate_id   = Column(Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    certificate_name = Column(String, nullable=True)
    organization   = Column(String, nullable=True)

    candidate      = relationship("Candidate", back_populates="certifications")

    def __repr__(self) -> str:
        return f"<Certification id={self.id} cand={self.candidate_id} name={self.certificate_name!r}>"

class Attachment(Base):
    __tablename__ = "attachments"

    id           = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False)
    type         = Column(String, nullable=True)    # 'pdf','docx'
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), onupdate=func.now())

    candidate    = relationship("Candidate", back_populates="attachments")

    def __repr__(self) -> str:
        return f"<Attachment id={self.id} cand={self.candidate_id} type={self.type!r}>"

# ---------------- Bootstrap ----------------
def create_all(url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/scan_cv"):
    engine = get_engine(url)
    Base.metadata.create_all(engine)
    return engine

if __name__ == "__main__":
    engine = create_all()
    SessionLocal.configure(bind=engine)
    print("Tables created.")
