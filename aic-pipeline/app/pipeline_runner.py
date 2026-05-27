import sys
from threading import Lock
from time import perf_counter
import numpy as np
import pandas as pd

sys.path.insert(0, "/app")

# aic_pipeline.py must be copied to /app (container root) — see Dockerfile
from aic_pipeline import (
    DEFAULT_SINGLE_ANALYSIS_NORMALIZATION_SCALES,
    EmbeddingBackend,
    compute_PI,
    compute_UI_OI,
    fit_weights_and_aic,
    safe_text,
)

_backend = None  # module-level singleton; loaded once at startup
_backend_lock = Lock()

DEFAULT_KEYWORDS = [
    "however", "although", "because", "why", "how", "compare",
    "contrast", "analyze", "evaluate", "critique", "moreover",
    "therefore", "consequently", "alternatively", "nevertheless",
]


def preload_model():
    global _backend
    with _backend_lock:
        if _backend is not None:
            return

        preferred_backend = EmbeddingBackend(prefer="sbert", sbert_model="paraphrase-multilingual-mpnet-base-v2")
        try:
            preferred_backend.fit(["warmup text for initialization"])
            _backend = preferred_backend
            print("[pipeline] Embedding backend initialized: sbert", flush=True)
        except Exception as exc:
            fallback_backend = EmbeddingBackend(prefer="tfidf")
            fallback_backend.fit(["warmup text for initialization"])
            _backend = fallback_backend
            print(f"[pipeline] Embedding fallback activated: tfidf ({exc})", flush=True)


def run_analysis(payload: dict) -> dict:
    global _backend
    try:
        pipeline_steps = []

        def record_step(name: str, seconds: float, status: str = "success"):
            pipeline_steps.append({
                "name": name,
                "status": status,
                "seconds": round(seconds, 3),
            })

        if _backend is None:
            preload_model()

        data_load_start = perf_counter()
        sub = payload["submission"]
        cfg = payload["config"]

        df = pd.DataFrame([{
            "sample_id": sub.get("sample_id", "x"),
            "course": sub.get("course", "default"),
            "student_id": sub.get("student_id", "x"),
            "chatgpt_before": safe_text(sub["chatgpt_before"]),
            "user": safe_text(sub["user"]),
            "essay": safe_text(sub["essay"]),
            "rating": np.nan,
        }])
        record_step("Data Load", perf_counter() - data_load_start)

        preprocess_start = perf_counter()
        keywords = cfg.get("critical_keywords") or DEFAULT_KEYWORDS
        pi_weights = cfg.get("pi_weights", [0.4, 0.3, 0.3])
        record_step("Preprocess", perf_counter() - preprocess_start)

        pi_start = perf_counter()
        df = compute_PI(
            df,
            keywords,
            weights=pi_weights,
            normalization="saturating_ratio",
            normalization_scales=DEFAULT_SINGLE_ANALYSIS_NORMALIZATION_SCALES,
        )
        record_step("PI", perf_counter() - pi_start)

        pipeline_cfg = {
            "ui_oi": {
                "topic_score_alpha": cfg.get("topic_score_alpha", 1.0),
                "topic_score_beta": cfg.get("topic_score_beta", 1.0),
                "min_course_samples": 1,
                "normalization": "saturating_ratio",
                "normalization_scales": DEFAULT_SINGLE_ANALYSIS_NORMALIZATION_SCALES,
                "reuse_fitted_sbert": True,
            }
        }
        with _backend_lock:
            df = compute_UI_OI(df, _backend, pipeline_cfg)
        ui_oi_timings = df.attrs.get("pipeline_timings", {})
        record_step("Embedding", ui_oi_timings.get("Embedding", 0.0))
        record_step("UI/OI", ui_oi_timings.get("UI/OI", 0.0))

        weights_cfg = {
            "weights": {
                "mode": "equal",
                "clip_negative": True,
                "min_ratings": 10,
                "n_folds": 5,
            }
        }
        aic_start = perf_counter()
        df, w = fit_weights_and_aic(df, weights_cfg)
        record_step("AIC fit", perf_counter() - aic_start)

        validation_start = perf_counter()
        row = df.iloc[0]

        def _f(col):
            v = row.get(col)
            return float(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else 0.0

        def _i(col):
            v = row.get(col)
            return int(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else 0
        record_step("Validation", perf_counter() - validation_start)

        return {
            "job_id": payload["job_id"],
            "pi": _f("PI"),
            "ui": _f("UI"),
            "oi": _f("OI"),
            "aic": _f("AIC"),
            "topic_score": _f("topic_score"),
            "weight_pi": float(w[0]),
            "weight_ui": float(w[1]),
            "weight_oi": float(w[2]),
            "pi_depth_tokens": _i("pi_depth_tokens"),
            "pi_depth_norm": _f("pi_depth_norm"),
            "pi_critical_ratio": _f("pi_critical_ratio"),
            "pi_avg_sent_len": _f("pi_avg_sent_len"),
            "pi_ttr": _f("pi_ttr"),
            "pi_complexity": _f("pi_complexity"),
            "ui_cos_similarity": _f("ui_cos_similarity"),
            "ui_distance": _f("ui_distance"),
            "ui_newinfo_ratio": _f("ui_newinfo_ratio"),
            "oi_topic_score_raw": _f("topic_score"),
            "embedding_backend": _backend.kind if _backend else "unknown",
            "pipeline_steps": pipeline_steps,
        }
    except Exception as exc:
        backend_name = _backend.kind if _backend else "uninitialized"
        raise RuntimeError(f"run_analysis failed (embedding_backend={backend_name}): {exc}") from exc
