import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timezone
from time import perf_counter

from fastapi import HTTPException
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.db_models import Assignment, BenchmarkRun, BenchmarkRunItem, Submission, User
from app.schemas.benchmark import BenchmarkRunCreate
from app.services.job_service import PIPELINE_VERSION, _build_backend_info
from app.services.pipeline_client import call_pipeline


async def create_benchmark_run(db: AsyncSession, body: BenchmarkRunCreate) -> dict:
    rows = (await db.execute(
        select(Submission, Assignment, User)
        .join(Assignment, Submission.assignment_id == Assignment.id)
        .join(User, Submission.student_id == User.id)
        .order_by(desc(Submission.submitted_at), desc(Submission.id))
        .limit(body.sample_limit)
    )).all()
    if not rows:
        raise HTTPException(status_code=409, detail="No submissions are available for benchmark")

    warmup_count = min(body.warmup_count, len(rows))
    snapshot_items = [
        {
            "submission_id": sub.id,
            "assignment_id": sub.assignment_id,
            "student_id": sub.student_id,
            "submitted_at": sub.submitted_at.isoformat() if sub.submitted_at else None,
        }
        for sub, _assignment, _student in rows
    ]
    dataset_snapshot = {
        "source": "recent_submissions",
        "limit": body.sample_limit,
        "count": len(snapshot_items),
        "submission_ids": [item["submission_id"] for item in snapshot_items],
        "items": snapshot_items,
    }
    dataset_hash = _stable_hash(dataset_snapshot)
    backend_info = _build_backend_info()

    run = BenchmarkRun(
        run_id=_make_benchmark_run_id(),
        label=body.label,
        status="pending",
        dataset_snapshot=dataset_snapshot,
        dataset_hash=dataset_hash,
        pipeline_version=PIPELINE_VERSION,
        config_hash=backend_info.get("configHash"),
        code_version=PIPELINE_VERSION,
        warmup_excluded_count=warmup_count,
        total_items=len(rows),
        processed_items=0,
        failed_items=0,
        stage_runtime_totals={},
        data_health_summary={},
    )
    db.add(run)
    await db.flush()

    for index, (sub, _assignment, _student) in enumerate(rows):
        db.add(BenchmarkRunItem(
            benchmark_run_id=run.id,
            submission_id=sub.id,
            sample_index=index,
            is_warmup=index < warmup_count,
            status="pending",
        ))

    await db.commit()
    await db.refresh(run)

    asyncio.create_task(_run_benchmark(run.run_id))

    return {
        "run_id": run.run_id,
        "status": run.status,
        "total": run.total_items,
        "warmup_excluded_count": run.warmup_excluded_count,
        "dataset_hash": run.dataset_hash,
        "created_at": run.created_at,
    }


async def list_benchmark_runs(db: AsyncSession, limit: int = 20) -> dict:
    limit = max(1, min(limit, 100))
    runs = list((await db.execute(
        select(BenchmarkRun)
        .order_by(desc(BenchmarkRun.created_at), desc(BenchmarkRun.id))
        .limit(limit)
    )).scalars().all())
    return {
        "runs": [_serialize_run_summary(run) for run in runs],
    }


async def get_benchmark_run_detail(db: AsyncSession, run_id: str) -> dict:
    run = (await db.execute(
        select(BenchmarkRun).where(BenchmarkRun.run_id == run_id)
    )).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail=f"Benchmark run {run_id} was not found")

    items = list((await db.execute(
        select(BenchmarkRunItem)
        .where(BenchmarkRunItem.benchmark_run_id == run.id)
        .order_by(BenchmarkRunItem.sample_index)
    )).scalars().all())
    return {
        **_serialize_run_summary(run),
        "pipeline_version": run.pipeline_version,
        "config_hash": run.config_hash,
        "code_version": run.code_version,
        "dataset_snapshot": run.dataset_snapshot or {},
        "stage_runtime_totals": run.stage_runtime_totals or {},
        "data_health_summary": run.data_health_summary or {},
        "error_message": run.error_message,
        "items": [_serialize_run_item(item) for item in items],
    }


async def compare_benchmark_runs(db: AsyncSession, baseline_run_id: str, optimized_run_id: str) -> dict:
    baseline = await _get_benchmark_run_or_404(db, baseline_run_id)
    optimized = await _get_benchmark_run_or_404(db, optimized_run_id)
    baseline_items = await _get_benchmark_items(db, baseline.id)
    optimized_items = await _get_benchmark_items(db, optimized.id)

    warnings = []
    same_dataset = baseline.dataset_hash == optimized.dataset_hash
    if not same_dataset:
        warnings.append("Dataset snapshots differ; compare runtime and quality changes cautiously.")
    for role, run in (("baseline", baseline), ("optimized", optimized)):
        if run.status != "completed":
            warnings.append(f"{role} run status is {run.status}; aggregate metrics may be incomplete.")

    return {
        "baseline_run_id": baseline.run_id,
        "optimized_run_id": optimized.run_id,
        "same_dataset": same_dataset,
        "warnings": warnings,
        "runtime": {
            "p50": _compare_metric(baseline.p50_runtime_sec, optimized.p50_runtime_sec),
            "p95": _compare_metric(baseline.p95_runtime_sec, optimized.p95_runtime_sec),
            "avg": _compare_metric(baseline.avg_runtime_sec, optimized.avg_runtime_sec),
        },
        "failure_rate": _compare_metric(baseline.failure_rate, optimized.failure_rate),
        "fallback_rate": _compare_metric(baseline.fallback_rate, optimized.fallback_rate),
        "data_health": _compare_dict_metrics(
            baseline.data_health_summary or {},
            optimized.data_health_summary or {},
        ),
        "stage_runtime": _compare_dict_metrics(
            baseline.stage_runtime_totals or {},
            optimized.stage_runtime_totals or {},
        ),
        "score_delta": _build_score_delta_summary(baseline_items, optimized_items),
        "outliers": _build_runtime_outliers(baseline_items, optimized_items),
    }


async def _run_benchmark(run_id: str):
    async with AsyncSessionLocal() as session:
        try:
            run = await _get_benchmark_run(session, run_id)
            await session.execute(
                update(BenchmarkRun)
                .where(BenchmarkRun.id == run.id)
                .values(status="running", started_at=datetime.now(timezone.utc), error_message=None)
            )
            await session.commit()

            items = list((await session.execute(
                select(BenchmarkRunItem)
                .where(BenchmarkRunItem.benchmark_run_id == run.id)
                .order_by(BenchmarkRunItem.sample_index)
            )).scalars().all())

            for item in items:
                await _run_benchmark_item(session, run.id, item)
                await _refresh_run_progress(session, run.id)

            await _finalize_benchmark_run(session, run.id)
        except Exception as exc:
            await session.rollback()
            run = (await session.execute(
                select(BenchmarkRun).where(BenchmarkRun.run_id == run_id)
            )).scalar_one_or_none()
            if run:
                await session.execute(
                    update(BenchmarkRun)
                    .where(BenchmarkRun.id == run.id)
                    .values(
                        status="failed",
                        error_message=str(exc),
                        completed_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()


async def _run_benchmark_item(session: AsyncSession, benchmark_run_id: int, item: BenchmarkRunItem):
    started_at = datetime.now(timezone.utc)
    await session.execute(
        update(BenchmarkRunItem)
        .where(BenchmarkRunItem.id == item.id)
        .values(status="running", started_at=started_at, error_message=None)
    )
    await session.commit()

    runtime_start = perf_counter()
    try:
        submission_payload = await _build_submission_payload(session, item.submission_id)
        result = await call_pipeline(f"benchmark-{benchmark_run_id}-{item.sample_index}", submission_payload)
        runtime_sec = perf_counter() - runtime_start
        await session.execute(
            update(BenchmarkRunItem)
            .where(BenchmarkRunItem.id == item.id)
            .values(
                status="completed",
                metric_snapshot=_build_metric_snapshot(result),
                runtime_sec=round(runtime_sec, 3),
                embedding_backend=result.get("embedding_backend"),
                pipeline_steps=result.get("pipeline_steps") or [],
                completed_at=datetime.now(timezone.utc),
            )
        )
    except Exception as exc:
        runtime_sec = perf_counter() - runtime_start
        await session.execute(
            update(BenchmarkRunItem)
            .where(BenchmarkRunItem.id == item.id)
            .values(
                status="failed",
                runtime_sec=round(runtime_sec, 3),
                error_message=str(exc),
                completed_at=datetime.now(timezone.utc),
            )
        )
    await session.commit()


async def _build_submission_payload(session: AsyncSession, submission_id: int | None) -> dict:
    if submission_id is None:
        raise ValueError("Benchmark item is not linked to a submission")

    row = (await session.execute(
        select(Submission, Assignment, User)
        .join(Assignment, Submission.assignment_id == Assignment.id)
        .join(User, Submission.student_id == User.id)
        .where(Submission.id == submission_id)
    )).first()
    if not row:
        raise ValueError(f"Submission {submission_id} not found")

    sub, assignment, student = row
    return {
        "submission_id": sub.id,
        "course_code": assignment.course_code or "default",
        "assignment_title": assignment.title,
        "user_id_str": student.user_id_str,
        "chatgpt_before": sub.chatgpt_before,
        "user_prompt": sub.user_prompt,
        "essay": sub.essay,
    }


async def _refresh_run_progress(session: AsyncSession, benchmark_run_id: int):
    items = list((await session.execute(
        select(BenchmarkRunItem).where(BenchmarkRunItem.benchmark_run_id == benchmark_run_id)
    )).scalars().all())
    processed = sum(1 for item in items if item.status in ("completed", "failed", "skipped"))
    failed = sum(1 for item in items if item.status == "failed")
    await session.execute(
        update(BenchmarkRun)
        .where(BenchmarkRun.id == benchmark_run_id)
        .values(processed_items=processed, failed_items=failed)
    )
    await session.commit()


async def _finalize_benchmark_run(session: AsyncSession, benchmark_run_id: int):
    items = list((await session.execute(
        select(BenchmarkRunItem)
        .where(BenchmarkRunItem.benchmark_run_id == benchmark_run_id)
        .order_by(BenchmarkRunItem.sample_index)
    )).scalars().all())

    included_items = [item for item in items if not item.is_warmup]
    completed_items = [item for item in included_items if item.status == "completed"]
    failed_count = sum(1 for item in included_items if item.status == "failed")
    runtimes = [item.runtime_sec for item in completed_items if item.runtime_sec is not None]
    total_included = len(included_items)
    fallback_count = sum(1 for item in completed_items if (item.embedding_backend or "").lower() == "tfidf")

    await session.execute(
        update(BenchmarkRun)
        .where(BenchmarkRun.id == benchmark_run_id)
        .values(
            status="completed",
            processed_items=sum(1 for item in items if item.status in ("completed", "failed", "skipped")),
            failed_items=sum(1 for item in items if item.status == "failed"),
            p50_runtime_sec=_percentile(runtimes, 50),
            p95_runtime_sec=_percentile(runtimes, 95),
            avg_runtime_sec=round(sum(runtimes) / len(runtimes), 3) if runtimes else None,
            failure_rate=round(failed_count / total_included * 100, 1) if total_included else 0.0,
            fallback_rate=round(fallback_count / total_included * 100, 1) if total_included else 0.0,
            stage_runtime_totals=_sum_pipeline_steps(completed_items),
            data_health_summary=_build_data_health_summary(items),
            completed_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()


async def _get_benchmark_run(session: AsyncSession, run_id: str) -> BenchmarkRun:
    run = (await session.execute(
        select(BenchmarkRun).where(BenchmarkRun.run_id == run_id)
    )).scalar_one_or_none()
    if not run:
        raise ValueError(f"Benchmark run {run_id} was not found")
    return run


async def _get_benchmark_run_or_404(session: AsyncSession, run_id: str) -> BenchmarkRun:
    run = (await session.execute(
        select(BenchmarkRun).where(BenchmarkRun.run_id == run_id)
    )).scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail=f"Benchmark run {run_id} was not found")
    return run


async def _get_benchmark_items(session: AsyncSession, benchmark_run_id: int) -> list[BenchmarkRunItem]:
    return list((await session.execute(
        select(BenchmarkRunItem)
        .where(BenchmarkRunItem.benchmark_run_id == benchmark_run_id)
        .order_by(BenchmarkRunItem.sample_index)
    )).scalars().all())


def _build_metric_snapshot(result: dict) -> dict:
    return {
        "scores": {
            "pi": _scale_score(result.get("pi")),
            "ui": _scale_score(result.get("ui")),
            "oi": _scale_score(result.get("oi")),
            "aic": _scale_score(result.get("aic")),
            "topic": _scale_score(result.get("topic_score")),
        },
        "raw": {
            "pi": result.get("pi"),
            "ui": result.get("ui"),
            "oi": result.get("oi"),
            "aic": result.get("aic"),
            "topic_score": result.get("topic_score"),
            "weight_pi": result.get("weight_pi"),
            "weight_ui": result.get("weight_ui"),
            "weight_oi": result.get("weight_oi"),
            "pi_depth_tokens": result.get("pi_depth_tokens"),
            "pi_depth_norm": result.get("pi_depth_norm"),
            "pi_critical_ratio": result.get("pi_critical_ratio"),
            "pi_avg_sent_len": result.get("pi_avg_sent_len"),
            "pi_ttr": result.get("pi_ttr"),
            "pi_complexity": result.get("pi_complexity"),
            "ui_cos_similarity": result.get("ui_cos_similarity"),
            "ui_distance": result.get("ui_distance"),
            "ui_newinfo_ratio": result.get("ui_newinfo_ratio"),
            "oi_topic_score_raw": result.get("oi_topic_score_raw"),
        },
    }


def _build_data_health_summary(items: list[BenchmarkRunItem]) -> dict:
    return {
        "total": len(items),
        "warmupExcluded": sum(1 for item in items if item.is_warmup),
        "completed": sum(1 for item in items if item.status == "completed"),
        "failed": sum(1 for item in items if item.status == "failed"),
        "skipped": sum(1 for item in items if item.status == "skipped"),
    }


def _sum_pipeline_steps(items: list[BenchmarkRunItem]) -> dict:
    totals = {}
    for item in items:
        for step in item.pipeline_steps or []:
            name = str(step.get("name") or "Unknown")
            totals[name] = round(totals.get(name, 0.0) + float(step.get("seconds") or 0.0), 3)
    return totals


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    rank = (len(ordered) - 1) * (percentile / 100)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 3)


def _scale_score(value) -> int | None:
    if value is None:
        return None
    return round(float(value) * 100)


def _stable_hash(value: dict) -> str:
    return hashlib.sha1(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def _make_benchmark_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"BENCH-{stamp}-{uuid.uuid4().hex[:8]}"


def _compare_metric(baseline, optimized) -> dict:
    baseline_value = _to_float_or_none(baseline)
    optimized_value = _to_float_or_none(optimized)
    if baseline_value is None or optimized_value is None:
        return {
            "baseline": baseline_value,
            "optimized": optimized_value,
            "delta": None,
            "percent_change": None,
        }

    delta = round(optimized_value - baseline_value, 3)
    percent_change = None
    if baseline_value != 0:
        percent_change = round(delta / baseline_value * 100, 1)
    return {
        "baseline": baseline_value,
        "optimized": optimized_value,
        "delta": delta,
        "percent_change": percent_change,
    }


def _compare_dict_metrics(baseline: dict, optimized: dict) -> dict:
    keys = sorted(set(baseline.keys()) | set(optimized.keys()))
    return {
        key: _compare_metric(baseline.get(key), optimized.get(key))
        for key in keys
        if _to_float_or_none(baseline.get(key)) is not None or _to_float_or_none(optimized.get(key)) is not None
    }


def _build_runtime_outliers(
    baseline_items: list[BenchmarkRunItem],
    optimized_items: list[BenchmarkRunItem],
    limit: int = 10,
) -> list[dict]:
    baseline_by_submission = {
        item.submission_id: item
        for item in baseline_items
        if item.submission_id is not None and not item.is_warmup
    }
    optimized_by_submission = {
        item.submission_id: item
        for item in optimized_items
        if item.submission_id is not None and not item.is_warmup
    }

    outliers = []
    for submission_id in sorted(set(baseline_by_submission) & set(optimized_by_submission)):
        baseline = baseline_by_submission[submission_id]
        optimized = optimized_by_submission[submission_id]
        baseline_runtime = _to_float_or_none(baseline.runtime_sec)
        optimized_runtime = _to_float_or_none(optimized.runtime_sec)
        if baseline_runtime is None or optimized_runtime is None:
            continue

        delta = round(optimized_runtime - baseline_runtime, 3)
        percent_change = round(delta / baseline_runtime * 100, 1) if baseline_runtime != 0 else None
        outliers.append({
            "submission_id": submission_id,
            "baseline_runtime_sec": baseline_runtime,
            "optimized_runtime_sec": optimized_runtime,
            "delta_runtime_sec": delta,
            "percent_change": percent_change,
            "baseline_status": baseline.status,
            "optimized_status": optimized.status,
        })

    outliers.sort(key=lambda item: abs(item["delta_runtime_sec"] or 0), reverse=True)
    return outliers[:limit]


def _build_score_delta_summary(
    baseline_items: list[BenchmarkRunItem],
    optimized_items: list[BenchmarkRunItem],
    limit: int = 10,
) -> dict:
    baseline_by_submission = {
        item.submission_id: item
        for item in baseline_items
        if item.submission_id is not None and not item.is_warmup and item.status == "completed"
    }
    optimized_by_submission = {
        item.submission_id: item
        for item in optimized_items
        if item.submission_id is not None and not item.is_warmup and item.status == "completed"
    }
    common_submission_ids = sorted(set(baseline_by_submission) & set(optimized_by_submission))
    metric_names = ("pi", "ui", "oi", "aic", "topic")
    deltas_by_metric = {name: [] for name in metric_names}
    outliers = []

    for submission_id in common_submission_ids:
        baseline_scores = _snapshot_scores(baseline_by_submission[submission_id])
        optimized_scores = _snapshot_scores(optimized_by_submission[submission_id])
        submission_deltas = {}
        max_abs_delta = 0.0

        for metric in metric_names:
            baseline_value = _to_float_or_none(baseline_scores.get(metric))
            optimized_value = _to_float_or_none(optimized_scores.get(metric))
            if baseline_value is None or optimized_value is None:
                continue
            delta = round(optimized_value - baseline_value, 3)
            deltas_by_metric[metric].append(delta)
            submission_deltas[metric] = {
                "baseline": baseline_value,
                "optimized": optimized_value,
                "delta": delta,
            }
            max_abs_delta = max(max_abs_delta, abs(delta))

        if submission_deltas:
            outliers.append({
                "submission_id": submission_id,
                "max_abs_delta": round(max_abs_delta, 3),
                "deltas": submission_deltas,
            })

    outliers.sort(key=lambda item: item["max_abs_delta"], reverse=True)

    return {
        "common_submission_count": len(common_submission_ids),
        "metrics": {
            metric: _summarize_score_deltas(deltas)
            for metric, deltas in deltas_by_metric.items()
        },
        "outliers": outliers[:limit],
    }


def _snapshot_scores(item: BenchmarkRunItem) -> dict:
    snapshot = item.metric_snapshot or {}
    scores = snapshot.get("scores") if isinstance(snapshot, dict) else {}
    return scores if isinstance(scores, dict) else {}


def _summarize_score_deltas(deltas: list[float]) -> dict:
    if not deltas:
        return {
            "count": 0,
            "avg_delta": None,
            "avg_abs_delta": None,
            "max_abs_delta": None,
            "within_1pt_count": 0,
            "within_3pt_count": 0,
        }

    abs_deltas = [abs(delta) for delta in deltas]
    return {
        "count": len(deltas),
        "avg_delta": round(sum(deltas) / len(deltas), 3),
        "avg_abs_delta": round(sum(abs_deltas) / len(abs_deltas), 3),
        "max_abs_delta": round(max(abs_deltas), 3),
        "within_1pt_count": sum(1 for delta in abs_deltas if delta <= 1.0),
        "within_3pt_count": sum(1 for delta in abs_deltas if delta <= 3.0),
    }


def _to_float_or_none(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _serialize_run_summary(run: BenchmarkRun) -> dict:
    return {
        "run_id": run.run_id,
        "label": run.label,
        "status": run.status,
        "processed": run.processed_items,
        "total": run.total_items,
        "failed": run.failed_items,
        "warmup_excluded_count": run.warmup_excluded_count,
        "dataset_hash": run.dataset_hash,
        "p50_runtime_sec": run.p50_runtime_sec,
        "p95_runtime_sec": run.p95_runtime_sec,
        "avg_runtime_sec": run.avg_runtime_sec,
        "failure_rate": run.failure_rate,
        "fallback_rate": run.fallback_rate,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "created_at": run.created_at,
    }


def _serialize_run_item(item: BenchmarkRunItem) -> dict:
    return {
        "submission_id": item.submission_id,
        "sample_index": item.sample_index,
        "is_warmup": item.is_warmup,
        "status": item.status,
        "runtime_sec": item.runtime_sec,
        "error_message": item.error_message,
        "embedding_backend": item.embedding_backend,
        "metric_snapshot": item.metric_snapshot or {},
        "pipeline_steps": item.pipeline_steps or [],
        "started_at": item.started_at,
        "completed_at": item.completed_at,
    }
