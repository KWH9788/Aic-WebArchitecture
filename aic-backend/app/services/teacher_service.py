from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List, Optional
from app.models.db_models import (
    User, Class, ClassEnrollment, Assignment, Submission, Metric, TeacherFeedback
)


def _status(aic: Optional[int]) -> str:
    if aic is None:
        return "pending"
    if aic >= 80:
        return "excellent"
    if aic >= 65:
        return "good"
    if aic >= 50:
        return "average"
    return "risk"


def _risk_types(pi: Optional[int], ui: Optional[int], oi: Optional[int]) -> List[str]:
    types = []
    if pi and pi < 50 and ui and ui < 50 and oi and oi < 50:
        types.append("all")
    elif pi and pi < 50:
        types.append("pi")
    elif ui and ui < 50:
        types.append("ui")
    elif oi and oi < 50:
        types.append("oi")
    return types


async def get_teacher_class(teacher_id: int, db: AsyncSession):
    result = await db.execute(
        select(Class).where(Class.teacher_id == teacher_id).limit(1)
    )
    return result.scalar_one_or_none()


async def assignment_belongs_to_class(assignment_id: int, class_id: int, db: AsyncSession) -> bool:
    result = await db.execute(
        select(Assignment.id).where(Assignment.id == assignment_id, Assignment.class_id == class_id).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def student_belongs_to_class(student_id: int, class_id: int, db: AsyncSession) -> bool:
    result = await db.execute(
        select(ClassEnrollment.id)
        .where(ClassEnrollment.student_id == student_id, ClassEnrollment.class_id == class_id)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def get_submission_counts_for_class(class_id: int, db: AsyncSession):
    result = await db.execute(
        select(Submission.student_id, func.count(Submission.id))
        .join(Assignment, Submission.assignment_id == Assignment.id)
        .where(Assignment.class_id == class_id)
        .group_by(Submission.student_id)
    )
    return {student_id: count for student_id, count in result.all()}


async def get_teacher_assignments(class_id: int, db: AsyncSession):
    submission_counts = (
        select(
            Submission.assignment_id.label("assignment_id"),
            func.count(Submission.id).label("submission_count"),
        )
        .group_by(Submission.assignment_id)
        .subquery()
    )
    analyzed_counts = (
        select(
            Submission.assignment_id.label("assignment_id"),
            func.count(Metric.id).label("analyzed_submission_count"),
        )
        .join(Metric, Metric.submission_id == Submission.id)
        .group_by(Submission.assignment_id)
        .subquery()
    )

    result = await db.execute(
        select(
            Assignment.id,
            Assignment.title,
            Assignment.course_code,
            Assignment.due_date,
            func.coalesce(submission_counts.c.submission_count, 0).label("submission_count"),
            func.coalesce(analyzed_counts.c.analyzed_submission_count, 0).label("analyzed_submission_count"),
        )
        .outerjoin(submission_counts, submission_counts.c.assignment_id == Assignment.id)
        .outerjoin(analyzed_counts, analyzed_counts.c.assignment_id == Assignment.id)
        .where(Assignment.class_id == class_id)
        .order_by(Assignment.due_date.asc(), Assignment.created_at.asc(), Assignment.id.asc())
    )
    return result.mappings().all()


async def get_all_student_latest_metrics(class_id: int, db: AsyncSession):
    # Get the latest assignment per class
    asgn_result = await db.execute(
        select(Assignment.id)
        .where(Assignment.class_id == class_id)
        .order_by(Assignment.created_at.desc())
        .limit(1)
    )
    latest_asgn = asgn_result.scalar_one_or_none()

    if not latest_asgn:
        return []

    result = await db.execute(
        select(User, Submission, Metric)
        .join(ClassEnrollment, ClassEnrollment.student_id == User.id)
        .outerjoin(Submission, (Submission.student_id == User.id) & (Submission.assignment_id == latest_asgn))
        .outerjoin(Metric, Metric.submission_id == Submission.id)
        .where(ClassEnrollment.class_id == class_id)
        .where(User.role == "student")
    )
    return result.all()


async def get_class_trend(class_id: int, db: AsyncSession):
    result = await db.execute(
        select(
            Assignment.id,
            Assignment.title,
            func.avg(Metric.aic_score).label("avg_aic"),
            func.avg(Metric.pi_score).label("avg_pi"),
        )
        .join(Submission, Submission.assignment_id == Assignment.id)
        .join(Metric, Metric.submission_id == Submission.id)
        .where(Assignment.class_id == class_id)
        .group_by(Assignment.id, Assignment.title)
        .order_by(Assignment.created_at.asc())
    )
    return result.all()


async def get_class_analyzed_metric_rows(class_id: int, db: AsyncSession):
    result = await db.execute(
        select(User, Assignment, Submission, Metric)
        .join(ClassEnrollment, ClassEnrollment.student_id == User.id)
        .join(Submission, Submission.student_id == User.id)
        .join(Assignment, Assignment.id == Submission.assignment_id)
        .join(Metric, Metric.submission_id == Submission.id)
        .where(ClassEnrollment.class_id == class_id)
        .where(Assignment.class_id == class_id)
        .where(User.role == "student")
        .where(Metric.aic_score.is_not(None))
        .order_by(Assignment.created_at.asc(), Assignment.id.asc(), User.user_id_str.asc())
    )
    return result.all()


async def get_student_all_submissions(student_id: int, class_id: int, db: AsyncSession):
    result = await db.execute(
        select(Submission, Assignment, Metric)
        .join(Assignment, Submission.assignment_id == Assignment.id)
        .outerjoin(Metric, Metric.submission_id == Submission.id)
        .where(Submission.student_id == student_id)
        .where(Assignment.class_id == class_id)
        .order_by(Assignment.created_at.asc())
    )
    return result.all()


async def get_student_feedback(student_id: int, assignment_id: int, db: AsyncSession):
    result = await db.execute(
        select(TeacherFeedback)
        .where(TeacherFeedback.student_id == student_id)
        .where(TeacherFeedback.assignment_id == assignment_id)
    )
    return result.scalar_one_or_none()


async def upsert_feedback(assignment_id: int, student_id: int, teacher_id: int, content: str, db: AsyncSession):
    result = await db.execute(
        select(TeacherFeedback)
        .where(TeacherFeedback.assignment_id == assignment_id)
        .where(TeacherFeedback.student_id == student_id)
    )
    fb = result.scalar_one_or_none()
    if fb:
        fb.content = content
        fb.teacher_id = teacher_id
    else:
        fb = TeacherFeedback(
            assignment_id=assignment_id,
            student_id=student_id,
            teacher_id=teacher_id,
            content=content,
        )
        db.add(fb)
    await db.commit()
    await db.refresh(fb)
    return fb


def build_aic_distribution(scores: List[Optional[int]]) -> List[int]:
    buckets = [0] * 7  # <40, 40-50, 50-60, 60-70, 70-80, 80-90, 90+
    for s in scores:
        if s is None:
            continue
        if s < 40:
            buckets[0] += 1
        elif s < 50:
            buckets[1] += 1
        elif s < 60:
            buckets[2] += 1
        elif s < 70:
            buckets[3] += 1
        elif s < 80:
            buckets[4] += 1
        elif s < 90:
            buckets[5] += 1
        else:
            buckets[6] += 1
    return buckets
