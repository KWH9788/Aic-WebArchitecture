from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime


class BenchmarkRunCreate(BaseModel):
    label: Optional[str] = None
    sample_limit: int = Field(default=50, ge=1, le=50)
    warmup_count: int = Field(default=1, ge=0, le=3)


class BenchmarkRunCreated(BaseModel):
    run_id: str
    status: str
    total: int
    warmup_excluded_count: int
    dataset_hash: str
    created_at: datetime


class BenchmarkRunSummary(BaseModel):
    run_id: str
    label: Optional[str] = None
    status: str
    processed: int
    total: int
    failed: int
    warmup_excluded_count: int
    dataset_hash: Optional[str] = None
    p50_runtime_sec: Optional[float] = None
    p95_runtime_sec: Optional[float] = None
    avg_runtime_sec: Optional[float] = None
    failure_rate: Optional[float] = None
    fallback_rate: Optional[float] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime


class BenchmarkRunList(BaseModel):
    runs: list[BenchmarkRunSummary] = Field(default_factory=list)


class BenchmarkRunItemDetail(BaseModel):
    submission_id: Optional[int] = None
    sample_index: int
    is_warmup: bool
    status: str
    runtime_sec: Optional[float] = None
    error_message: Optional[str] = None
    embedding_backend: Optional[str] = None
    metric_snapshot: Optional[dict[str, Any]] = None
    pipeline_steps: list[dict[str, Any]] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class BenchmarkRunDetail(BenchmarkRunSummary):
    pipeline_version: Optional[str] = None
    config_hash: Optional[str] = None
    code_version: Optional[str] = None
    dataset_snapshot: Optional[dict[str, Any]] = None
    stage_runtime_totals: dict[str, float] = Field(default_factory=dict)
    data_health_summary: dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    items: list[BenchmarkRunItemDetail] = Field(default_factory=list)


class BenchmarkMetricComparison(BaseModel):
    baseline: Optional[float] = None
    optimized: Optional[float] = None
    delta: Optional[float] = None
    percent_change: Optional[float] = None


class BenchmarkComparisonOutlier(BaseModel):
    submission_id: Optional[int] = None
    baseline_runtime_sec: Optional[float] = None
    optimized_runtime_sec: Optional[float] = None
    delta_runtime_sec: Optional[float] = None
    percent_change: Optional[float] = None
    baseline_status: str
    optimized_status: str


class BenchmarkComparison(BaseModel):
    baseline_run_id: str
    optimized_run_id: str
    same_dataset: bool
    warnings: list[str] = Field(default_factory=list)
    runtime: dict[str, BenchmarkMetricComparison]
    failure_rate: BenchmarkMetricComparison
    fallback_rate: BenchmarkMetricComparison
    data_health: dict[str, BenchmarkMetricComparison]
    stage_runtime: dict[str, BenchmarkMetricComparison]
    score_delta: dict[str, Any] = Field(default_factory=dict)
    outliers: list[BenchmarkComparisonOutlier] = Field(default_factory=list)
