from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Boolean, Integer, String, Text, Enum, DateTime, Float, ForeignKey,
    UniqueConstraint, Index, func, JSON
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.security import EncryptedText


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id_str: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    role: Mapped[str] = mapped_column(Enum("student", "teacher", "admin"), nullable=False)
    name: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(EncryptedText)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    taught_classes: Mapped[list["Class"]] = relationship(back_populates="teacher")
    enrollments: Mapped[list["ClassEnrollment"]] = relationship(back_populates="student")
    submissions: Mapped[list["Submission"]] = relationship(back_populates="student")
    feedbacks_given: Mapped[list["TeacherFeedback"]] = relationship(
        back_populates="teacher", foreign_keys="TeacherFeedback.teacher_id"
    )
    feedbacks_received: Mapped[list["TeacherFeedback"]] = relationship(
        back_populates="student", foreign_keys="TeacherFeedback.student_id"
    )


class Class(Base):
    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    class_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    class_name: Mapped[str] = mapped_column(String(256), nullable=False)
    teacher_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    semester: Mapped[Optional[str]] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    teacher: Mapped["User"] = relationship(back_populates="taught_classes")
    enrollments: Mapped[list["ClassEnrollment"]] = relationship(back_populates="cls")
    assignments: Mapped[list["Assignment"]] = relationship(back_populates="cls")


class ClassEnrollment(Base):
    __tablename__ = "class_enrollments"
    __table_args__ = (UniqueConstraint("class_id", "student_id", name="uq_enrollment"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(Integer, ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    cls: Mapped["Class"] = relationship(back_populates="enrollments")
    student: Mapped["User"] = relationship(back_populates="enrollments")


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(Integer, ForeignKey("classes.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    course_code: Mapped[Optional[str]] = mapped_column(String(32))
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    cls: Mapped["Class"] = relationship(back_populates="assignments")
    submissions: Mapped[list["Submission"]] = relationship(back_populates="assignment")
    feedbacks: Mapped[list["TeacherFeedback"]] = relationship(back_populates="assignment")


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("assignment_id", "student_id", name="uq_submission"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assignment_id: Mapped[int] = mapped_column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    chatgpt_before: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    essay: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    assignment: Mapped["Assignment"] = relationship(back_populates="submissions")
    student: Mapped["User"] = relationship(back_populates="submissions")
    metrics: Mapped[Optional["Metric"]] = relationship(back_populates="submission", uselist=False)
    jobs: Mapped[list["AnalysisJob"]] = relationship(back_populates="submission")
    analysis_runs: Mapped[list["AnalysisRun"]] = relationship(back_populates="submission")
    benchmark_items: Mapped[list["BenchmarkRunItem"]] = relationship(back_populates="submission")


class Metric(Base):
    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), unique=True, nullable=False)
    pi_score: Mapped[Optional[int]] = mapped_column(Integer)
    ui_score: Mapped[Optional[int]] = mapped_column(Integer)
    oi_score: Mapped[Optional[int]] = mapped_column(Integer)
    aic_score: Mapped[Optional[int]] = mapped_column(Integer)
    topic_score: Mapped[Optional[int]] = mapped_column(Integer)
    weight_pi: Mapped[Optional[float]] = mapped_column(Float)
    weight_ui: Mapped[Optional[float]] = mapped_column(Float)
    weight_oi: Mapped[Optional[float]] = mapped_column(Float)
    pi_depth_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    pi_depth_norm: Mapped[Optional[float]] = mapped_column(Float)
    pi_critical_ratio: Mapped[Optional[float]] = mapped_column(Float)
    pi_avg_sent_len: Mapped[Optional[float]] = mapped_column(Float)
    pi_ttr: Mapped[Optional[float]] = mapped_column(Float)
    pi_complexity: Mapped[Optional[float]] = mapped_column(Float)
    ui_cos_similarity: Mapped[Optional[float]] = mapped_column(Float)
    ui_distance: Mapped[Optional[float]] = mapped_column(Float)
    ui_newinfo_ratio: Mapped[Optional[float]] = mapped_column(Float)
    oi_topic_score_raw: Mapped[Optional[float]] = mapped_column(Float)
    embedding_backend: Mapped[Optional[str]] = mapped_column(String(16))
    computed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    submission: Mapped["Submission"] = relationship(back_populates="metrics")


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_uuid: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    submission_id: Mapped[int] = mapped_column(Integer, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(Enum("pending", "running", "done", "failed"), default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    submission: Mapped["Submission"] = relationship(back_populates="jobs")


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        Index("idx_analysis_runs_created_at", "created_at"),
        Index("idx_analysis_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    job_uuid: Mapped[Optional[str]] = mapped_column(String(36), unique=True)
    submission_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("submissions.id", ondelete="SET NULL"))
    course: Mapped[Optional[str]] = mapped_column(String(32))
    assignment: Mapped[Optional[str]] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(Enum("running", "completed", "failed"), default="running")
    processed_rows: Mapped[int] = mapped_column(Integer, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, default=0)
    success_rate: Mapped[float] = mapped_column(Float, default=0.0)
    total_runtime_sec: Mapped[float] = mapped_column(Float, default=0.0)
    avg_runtime_per_sample: Mapped[float] = mapped_column(Float, default=0.0)
    data_health: Mapped[Optional[dict]] = mapped_column(JSON)
    backend_info: Mapped[Optional[dict]] = mapped_column(JSON)
    pipeline_steps: Mapped[Optional[list]] = mapped_column(JSON)
    readiness: Mapped[Optional[dict]] = mapped_column(JSON)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    submission: Mapped[Optional["Submission"]] = relationship(back_populates="analysis_runs")


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"
    __table_args__ = (
        Index("idx_benchmark_runs_created_at", "created_at"),
        Index("idx_benchmark_runs_status", "status"),
        Index("idx_benchmark_runs_dataset_hash", "dataset_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    label: Mapped[Optional[str]] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(Enum("pending", "running", "completed", "failed", "canceled"), default="pending")
    dataset_snapshot: Mapped[Optional[dict]] = mapped_column(JSON)
    dataset_hash: Mapped[Optional[str]] = mapped_column(String(64))
    pipeline_version: Mapped[Optional[str]] = mapped_column(String(64))
    config_hash: Mapped[Optional[str]] = mapped_column(String(64))
    code_version: Mapped[Optional[str]] = mapped_column(String(64))
    warmup_excluded_count: Mapped[int] = mapped_column(Integer, default=0)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    processed_items: Mapped[int] = mapped_column(Integer, default=0)
    failed_items: Mapped[int] = mapped_column(Integer, default=0)
    p50_runtime_sec: Mapped[Optional[float]] = mapped_column(Float)
    p95_runtime_sec: Mapped[Optional[float]] = mapped_column(Float)
    avg_runtime_sec: Mapped[Optional[float]] = mapped_column(Float)
    failure_rate: Mapped[Optional[float]] = mapped_column(Float)
    fallback_rate: Mapped[Optional[float]] = mapped_column(Float)
    stage_runtime_totals: Mapped[Optional[dict]] = mapped_column(JSON)
    data_health_summary: Mapped[Optional[dict]] = mapped_column(JSON)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    items: Mapped[list["BenchmarkRunItem"]] = relationship(back_populates="benchmark_run")


class BenchmarkRunItem(Base):
    __tablename__ = "benchmark_run_items"
    __table_args__ = (
        UniqueConstraint("benchmark_run_id", "sample_index", name="uq_benchmark_run_item_index"),
        UniqueConstraint("benchmark_run_id", "submission_id", name="uq_benchmark_run_item_submission"),
        Index("idx_benchmark_run_items_status", "status"),
        Index("idx_benchmark_run_items_submission_id", "submission_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    benchmark_run_id: Mapped[int] = mapped_column(Integer, ForeignKey("benchmark_runs.id", ondelete="CASCADE"), nullable=False)
    submission_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("submissions.id", ondelete="SET NULL"))
    sample_index: Mapped[int] = mapped_column(Integer, nullable=False)
    is_warmup: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(Enum("pending", "running", "completed", "failed", "skipped"), default="pending")
    metric_snapshot: Mapped[Optional[dict]] = mapped_column(JSON)
    runtime_sec: Mapped[Optional[float]] = mapped_column(Float)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    embedding_backend: Mapped[Optional[str]] = mapped_column(String(16))
    pipeline_steps: Mapped[Optional[list]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    benchmark_run: Mapped["BenchmarkRun"] = relationship(back_populates="items")
    submission: Mapped[Optional["Submission"]] = relationship(back_populates="benchmark_items")


class TeacherFeedback(Base):
    __tablename__ = "teacher_feedback"
    __table_args__ = (UniqueConstraint("assignment_id", "student_id", name="uq_feedback"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    assignment_id: Mapped[int] = mapped_column(Integer, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    teacher_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    assignment: Mapped["Assignment"] = relationship(back_populates="feedbacks")
    student: Mapped["User"] = relationship(back_populates="feedbacks_received", foreign_keys=[student_id])
    teacher: Mapped["User"] = relationship(back_populates="feedbacks_given", foreign_keys=[teacher_id])
