from __future__ import annotations

import os
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Iterable

import psycopg
import pymysql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pymysql.cursors import DictCursor

from app.validation import ValidationReport
from app.validation import collect_validation_report, format_validation_report


RAW_TABLES = [
    "raw_users",
    "raw_classes",
    "raw_assignments",
    "raw_submissions",
    "raw_metrics",
]


def required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def connect_source() -> pymysql.connections.Connection:
    return pymysql.connect(
        host=required_env("SOURCE_DB_HOST"),
        port=int(os.getenv("SOURCE_DB_PORT", "3306")),
        user=required_env("SOURCE_DB_USER"),
        password=required_env("SOURCE_DB_PASSWORD"),
        database=required_env("SOURCE_DB_NAME"),
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )


def connect_warehouse() -> psycopg.Connection:
    return psycopg.connect(
        host=required_env("WAREHOUSE_DB_HOST"),
        port=int(os.getenv("WAREHOUSE_DB_PORT", "5432")),
        user=required_env("WAREHOUSE_DB_USER"),
        password=required_env("WAREHOUSE_DB_PASSWORD"),
        dbname=required_env("WAREHOUSE_DB_NAME"),
        row_factory=dict_row,
    )


def execute_many(
    connection: psycopg.Connection,
    sql: str,
    rows: Iterable[dict[str, Any]],
) -> int:
    batch = list(rows)
    if not batch:
        return 0
    with connection.cursor() as cursor:
        cursor.executemany(sql, batch)
    return len(batch)


def fetch_all(source: pymysql.connections.Connection, sql: str) -> list[dict[str, Any]]:
    with source.cursor() as cursor:
        cursor.execute(sql)
        return list(cursor.fetchall())


def execute(connection: psycopg.Connection, sql: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(sql)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_run_history_schema(warehouse: psycopg.Connection) -> None:
    execute(
        warehouse,
        """
        CREATE TABLE IF NOT EXISTS elt_run_history (
            run_id BIGSERIAL PRIMARY KEY,
            started_at TIMESTAMPTZ NOT NULL,
            finished_at TIMESTAMPTZ NOT NULL,
            duration_ms INTEGER NOT NULL,
            status VARCHAR(16) NOT NULL,
            raw_loaded_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
            source_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
            warehouse_counts JSONB NOT NULL DEFAULT '{}'::jsonb,
            validation_failures JSONB NOT NULL DEFAULT '[]'::jsonb,
            error_message TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT chk_elt_run_history_status CHECK (
                status IN ('success', 'failed')
            )
        )
        """,
    )
    execute(
        warehouse,
        """
        CREATE INDEX IF NOT EXISTS idx_elt_run_history_started_at
        ON elt_run_history (started_at DESC)
        """,
    )
    execute(
        warehouse,
        """
        CREATE INDEX IF NOT EXISTS idx_elt_run_history_status
        ON elt_run_history (status)
        """,
    )


def insert_elt_run_history(
    warehouse: psycopg.Connection,
    *,
    started_at: datetime,
    status: str,
    raw_loaded_counts: dict[str, int],
    report: ValidationReport | None,
    error_message: str | None,
) -> None:
    finished_at = utc_now()
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    validation_failures = []
    if report is not None:
        validation_failures = [
            {"check_name": failure.check_name, "message": failure.message}
            for failure in report.failures
        ]

    with warehouse.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO elt_run_history (
                started_at,
                finished_at,
                duration_ms,
                status,
                raw_loaded_counts,
                source_counts,
                warehouse_counts,
                validation_failures,
                error_message
            ) VALUES (
                %(started_at)s,
                %(finished_at)s,
                %(duration_ms)s,
                %(status)s,
                %(raw_loaded_counts)s,
                %(source_counts)s,
                %(warehouse_counts)s,
                %(validation_failures)s,
                %(error_message)s
            )
            """,
            {
                "started_at": started_at,
                "finished_at": finished_at,
                "duration_ms": duration_ms,
                "status": status,
                "raw_loaded_counts": Jsonb(raw_loaded_counts),
                "source_counts": Jsonb(report.source_counts if report else {}),
                "warehouse_counts": Jsonb(report.warehouse_counts if report else {}),
                "validation_failures": Jsonb(validation_failures),
                "error_message": error_message,
            },
        )


def record_failed_run_history(
    *,
    started_at: datetime,
    raw_loaded_counts: dict[str, int],
    report: ValidationReport | None,
    error: Exception,
) -> None:
    try:
        with closing(connect_warehouse()) as warehouse:
            create_run_history_schema(warehouse)
            insert_elt_run_history(
                warehouse,
                started_at=started_at,
                status="failed",
                raw_loaded_counts=raw_loaded_counts,
                report=report,
                error_message=str(error),
            )
            warehouse.commit()
    except Exception as history_error:
        print(f"Failed to record ELT run history: {history_error}")


def create_schema(warehouse: psycopg.Connection) -> None:
    create_run_history_schema(warehouse)
    statements = [
        """
        CREATE TABLE IF NOT EXISTS raw_users (
            source_user_id INTEGER NOT NULL PRIMARY KEY,
            user_id_str VARCHAR(64) NOT NULL,
            role VARCHAR(16) NOT NULL,
            name TEXT NOT NULL,
            email TEXT,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            loaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_raw_users_role ON raw_users (role)",
        """
        CREATE TABLE IF NOT EXISTS raw_classes (
            source_class_id INTEGER NOT NULL PRIMARY KEY,
            class_code VARCHAR(32) NOT NULL,
            class_name VARCHAR(256) NOT NULL,
            source_teacher_id INTEGER NOT NULL,
            semester VARCHAR(32),
            created_at TIMESTAMP,
            loaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_raw_classes_teacher ON raw_classes (source_teacher_id)",
        """
        CREATE TABLE IF NOT EXISTS raw_assignments (
            source_assignment_id INTEGER NOT NULL PRIMARY KEY,
            source_class_id INTEGER NOT NULL,
            title VARCHAR(512) NOT NULL,
            description TEXT,
            course_code VARCHAR(32),
            due_date TIMESTAMP,
            created_at TIMESTAMP,
            loaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_raw_assignments_class ON raw_assignments (source_class_id)",
        """
        CREATE TABLE IF NOT EXISTS raw_submissions (
            source_submission_id INTEGER NOT NULL PRIMARY KEY,
            source_assignment_id INTEGER NOT NULL,
            source_student_id INTEGER NOT NULL,
            chatgpt_before TEXT NOT NULL,
            user_prompt TEXT NOT NULL,
            essay TEXT NOT NULL,
            submitted_at TIMESTAMP,
            loaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_raw_submission_assignment_student UNIQUE (
                source_assignment_id,
                source_student_id
            )
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_raw_submissions_student ON raw_submissions (source_student_id)",
        """
        CREATE TABLE IF NOT EXISTS raw_metrics (
            source_metric_id INTEGER NOT NULL PRIMARY KEY,
            source_submission_id INTEGER NOT NULL,
            pi_score SMALLINT,
            ui_score SMALLINT,
            oi_score SMALLINT,
            aic_score SMALLINT,
            topic_score SMALLINT,
            weight_pi DOUBLE PRECISION,
            weight_ui DOUBLE PRECISION,
            weight_oi DOUBLE PRECISION,
            pi_depth_tokens INTEGER,
            pi_depth_norm DOUBLE PRECISION,
            pi_critical_ratio DOUBLE PRECISION,
            pi_avg_sent_len DOUBLE PRECISION,
            pi_ttr DOUBLE PRECISION,
            pi_complexity DOUBLE PRECISION,
            ui_cos_similarity DOUBLE PRECISION,
            ui_distance DOUBLE PRECISION,
            ui_newinfo_ratio DOUBLE PRECISION,
            oi_topic_score_raw DOUBLE PRECISION,
            embedding_backend VARCHAR(16),
            computed_at TIMESTAMP,
            loaded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_raw_metrics_submission UNIQUE (source_submission_id)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS stg_submission_metrics (
            source_submission_id INTEGER NOT NULL PRIMARY KEY,
            source_assignment_id INTEGER NOT NULL,
            source_student_id INTEGER NOT NULL,
            source_class_id INTEGER NOT NULL,
            source_teacher_id INTEGER NOT NULL,
            class_code VARCHAR(32) NOT NULL,
            class_name VARCHAR(256) NOT NULL,
            assignment_title VARCHAR(512) NOT NULL,
            course_code VARCHAR(32),
            student_user_id_str VARCHAR(64) NOT NULL,
            student_name TEXT NOT NULL,
            teacher_user_id_str VARCHAR(64) NOT NULL,
            submitted_at TIMESTAMP,
            computed_at TIMESTAMP,
            pi_score SMALLINT,
            ui_score SMALLINT,
            oi_score SMALLINT,
            aic_score SMALLINT,
            topic_score SMALLINT,
            embedding_backend VARCHAR(16),
            transformed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_stg_assignment_student UNIQUE (
                source_assignment_id,
                source_student_id
            )
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_stg_class_assignment ON stg_submission_metrics (source_class_id, source_assignment_id)",
        """
        CREATE TABLE IF NOT EXISTS mart_student_assignment_metrics (
            source_assignment_id INTEGER NOT NULL,
            source_student_id INTEGER NOT NULL,
            source_submission_id INTEGER NOT NULL,
            source_class_id INTEGER NOT NULL,
            class_code VARCHAR(32) NOT NULL,
            class_name VARCHAR(256) NOT NULL,
            assignment_title VARCHAR(512) NOT NULL,
            course_code VARCHAR(32),
            student_user_id_str VARCHAR(64) NOT NULL,
            student_name TEXT NOT NULL,
            submitted_at TIMESTAMP,
            computed_at TIMESTAMP,
            pi_score SMALLINT,
            ui_score SMALLINT,
            oi_score SMALLINT,
            aic_score SMALLINT,
            topic_score SMALLINT,
            refreshed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (source_assignment_id, source_student_id)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_mart_student_metrics_class ON mart_student_assignment_metrics (source_class_id)",
        "CREATE INDEX IF NOT EXISTS idx_mart_student_metrics_student ON mart_student_assignment_metrics (source_student_id)",
        """
        CREATE TABLE IF NOT EXISTS mart_assignment_summary (
            source_assignment_id INTEGER NOT NULL PRIMARY KEY,
            source_class_id INTEGER NOT NULL,
            class_code VARCHAR(32) NOT NULL,
            class_name VARCHAR(256) NOT NULL,
            assignment_title VARCHAR(512) NOT NULL,
            course_code VARCHAR(32),
            submission_count INTEGER NOT NULL,
            avg_pi_score DOUBLE PRECISION,
            avg_ui_score DOUBLE PRECISION,
            avg_oi_score DOUBLE PRECISION,
            avg_aic_score DOUBLE PRECISION,
            avg_topic_score DOUBLE PRECISION,
            min_submitted_at TIMESTAMP,
            max_submitted_at TIMESTAMP,
            refreshed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_mart_assignment_summary_class ON mart_assignment_summary (source_class_id)",
        """
        CREATE TABLE IF NOT EXISTS mart_class_summary (
            source_class_id INTEGER NOT NULL PRIMARY KEY,
            class_code VARCHAR(32) NOT NULL,
            class_name VARCHAR(256) NOT NULL,
            source_teacher_id INTEGER NOT NULL,
            teacher_user_id_str VARCHAR(64) NOT NULL,
            assignment_count INTEGER NOT NULL,
            submission_count INTEGER NOT NULL,
            avg_pi_score DOUBLE PRECISION,
            avg_ui_score DOUBLE PRECISION,
            avg_oi_score DOUBLE PRECISION,
            avg_aic_score DOUBLE PRECISION,
            avg_topic_score DOUBLE PRECISION,
            refreshed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ]
    for statement in statements:
        execute(warehouse, statement)


def load_raw(source: pymysql.connections.Connection, warehouse: psycopg.Connection) -> dict[str, int]:
    extracts = {
        "raw_users": (
            """
            SELECT
                id AS source_user_id,
                user_id_str,
                role,
                name,
                email,
                created_at,
                updated_at
            FROM users
            """,
            """
            INSERT INTO raw_users (
                source_user_id,
                user_id_str,
                role,
                name,
                email,
                created_at,
                updated_at
            ) VALUES (
                %(source_user_id)s,
                %(user_id_str)s,
                %(role)s,
                %(name)s,
                %(email)s,
                %(created_at)s,
                %(updated_at)s
            )
            ON CONFLICT (source_user_id) DO UPDATE SET
                user_id_str = EXCLUDED.user_id_str,
                role = EXCLUDED.role,
                name = EXCLUDED.name,
                email = EXCLUDED.email,
                created_at = EXCLUDED.created_at,
                updated_at = EXCLUDED.updated_at,
                loaded_at = CURRENT_TIMESTAMP
            """,
        ),
        "raw_classes": (
            """
            SELECT
                id AS source_class_id,
                class_code,
                class_name,
                teacher_id AS source_teacher_id,
                semester,
                created_at
            FROM classes
            """,
            """
            INSERT INTO raw_classes (
                source_class_id,
                class_code,
                class_name,
                source_teacher_id,
                semester,
                created_at
            ) VALUES (
                %(source_class_id)s,
                %(class_code)s,
                %(class_name)s,
                %(source_teacher_id)s,
                %(semester)s,
                %(created_at)s
            )
            ON CONFLICT (source_class_id) DO UPDATE SET
                class_code = EXCLUDED.class_code,
                class_name = EXCLUDED.class_name,
                source_teacher_id = EXCLUDED.source_teacher_id,
                semester = EXCLUDED.semester,
                created_at = EXCLUDED.created_at,
                loaded_at = CURRENT_TIMESTAMP
            """,
        ),
        "raw_assignments": (
            """
            SELECT
                id AS source_assignment_id,
                class_id AS source_class_id,
                title,
                description,
                course_code,
                due_date,
                created_at
            FROM assignments
            """,
            """
            INSERT INTO raw_assignments (
                source_assignment_id,
                source_class_id,
                title,
                description,
                course_code,
                due_date,
                created_at
            ) VALUES (
                %(source_assignment_id)s,
                %(source_class_id)s,
                %(title)s,
                %(description)s,
                %(course_code)s,
                %(due_date)s,
                %(created_at)s
            )
            ON CONFLICT (source_assignment_id) DO UPDATE SET
                source_class_id = EXCLUDED.source_class_id,
                title = EXCLUDED.title,
                description = EXCLUDED.description,
                course_code = EXCLUDED.course_code,
                due_date = EXCLUDED.due_date,
                created_at = EXCLUDED.created_at,
                loaded_at = CURRENT_TIMESTAMP
            """,
        ),
        "raw_submissions": (
            """
            SELECT
                id AS source_submission_id,
                assignment_id AS source_assignment_id,
                student_id AS source_student_id,
                chatgpt_before,
                user_prompt,
                essay,
                submitted_at
            FROM submissions
            """,
            """
            INSERT INTO raw_submissions (
                source_submission_id,
                source_assignment_id,
                source_student_id,
                chatgpt_before,
                user_prompt,
                essay,
                submitted_at
            ) VALUES (
                %(source_submission_id)s,
                %(source_assignment_id)s,
                %(source_student_id)s,
                %(chatgpt_before)s,
                %(user_prompt)s,
                %(essay)s,
                %(submitted_at)s
            )
            ON CONFLICT (source_submission_id) DO UPDATE SET
                source_assignment_id = EXCLUDED.source_assignment_id,
                source_student_id = EXCLUDED.source_student_id,
                chatgpt_before = EXCLUDED.chatgpt_before,
                user_prompt = EXCLUDED.user_prompt,
                essay = EXCLUDED.essay,
                submitted_at = EXCLUDED.submitted_at,
                loaded_at = CURRENT_TIMESTAMP
            """,
        ),
        "raw_metrics": (
            """
            SELECT
                id AS source_metric_id,
                submission_id AS source_submission_id,
                pi_score,
                ui_score,
                oi_score,
                aic_score,
                topic_score,
                weight_pi,
                weight_ui,
                weight_oi,
                pi_depth_tokens,
                pi_depth_norm,
                pi_critical_ratio,
                pi_avg_sent_len,
                pi_ttr,
                pi_complexity,
                ui_cos_similarity,
                ui_distance,
                ui_newinfo_ratio,
                oi_topic_score_raw,
                embedding_backend,
                computed_at
            FROM metrics
            """,
            """
            INSERT INTO raw_metrics (
                source_metric_id,
                source_submission_id,
                pi_score,
                ui_score,
                oi_score,
                aic_score,
                topic_score,
                weight_pi,
                weight_ui,
                weight_oi,
                pi_depth_tokens,
                pi_depth_norm,
                pi_critical_ratio,
                pi_avg_sent_len,
                pi_ttr,
                pi_complexity,
                ui_cos_similarity,
                ui_distance,
                ui_newinfo_ratio,
                oi_topic_score_raw,
                embedding_backend,
                computed_at
            ) VALUES (
                %(source_metric_id)s,
                %(source_submission_id)s,
                %(pi_score)s,
                %(ui_score)s,
                %(oi_score)s,
                %(aic_score)s,
                %(topic_score)s,
                %(weight_pi)s,
                %(weight_ui)s,
                %(weight_oi)s,
                %(pi_depth_tokens)s,
                %(pi_depth_norm)s,
                %(pi_critical_ratio)s,
                %(pi_avg_sent_len)s,
                %(pi_ttr)s,
                %(pi_complexity)s,
                %(ui_cos_similarity)s,
                %(ui_distance)s,
                %(ui_newinfo_ratio)s,
                %(oi_topic_score_raw)s,
                %(embedding_backend)s,
                %(computed_at)s
            )
            ON CONFLICT (source_metric_id) DO UPDATE SET
                source_submission_id = EXCLUDED.source_submission_id,
                pi_score = EXCLUDED.pi_score,
                ui_score = EXCLUDED.ui_score,
                oi_score = EXCLUDED.oi_score,
                aic_score = EXCLUDED.aic_score,
                topic_score = EXCLUDED.topic_score,
                weight_pi = EXCLUDED.weight_pi,
                weight_ui = EXCLUDED.weight_ui,
                weight_oi = EXCLUDED.weight_oi,
                pi_depth_tokens = EXCLUDED.pi_depth_tokens,
                pi_depth_norm = EXCLUDED.pi_depth_norm,
                pi_critical_ratio = EXCLUDED.pi_critical_ratio,
                pi_avg_sent_len = EXCLUDED.pi_avg_sent_len,
                pi_ttr = EXCLUDED.pi_ttr,
                pi_complexity = EXCLUDED.pi_complexity,
                ui_cos_similarity = EXCLUDED.ui_cos_similarity,
                ui_distance = EXCLUDED.ui_distance,
                ui_newinfo_ratio = EXCLUDED.ui_newinfo_ratio,
                oi_topic_score_raw = EXCLUDED.oi_topic_score_raw,
                embedding_backend = EXCLUDED.embedding_backend,
                computed_at = EXCLUDED.computed_at,
                loaded_at = CURRENT_TIMESTAMP
            """,
        ),
    }

    counts: dict[str, int] = {}
    for table_name in RAW_TABLES:
        select_sql, insert_sql = extracts[table_name]
        rows = fetch_all(source, select_sql)
        counts[table_name] = execute_many(warehouse, insert_sql, rows)
    return counts


def transform(warehouse: psycopg.Connection) -> None:
    execute(
        warehouse,
        """
        INSERT INTO stg_submission_metrics (
            source_submission_id,
            source_assignment_id,
            source_student_id,
            source_class_id,
            source_teacher_id,
            class_code,
            class_name,
            assignment_title,
            course_code,
            student_user_id_str,
            student_name,
            teacher_user_id_str,
            submitted_at,
            computed_at,
            pi_score,
            ui_score,
            oi_score,
            aic_score,
            topic_score,
            embedding_backend
        )
        SELECT
            s.source_submission_id,
            s.source_assignment_id,
            s.source_student_id,
            a.source_class_id,
            c.source_teacher_id,
            c.class_code,
            c.class_name,
            a.title,
            a.course_code,
            student.user_id_str,
            student.name,
            teacher.user_id_str,
            s.submitted_at,
            m.computed_at,
            m.pi_score,
            m.ui_score,
            m.oi_score,
            m.aic_score,
            m.topic_score,
            m.embedding_backend
        FROM raw_submissions s
        JOIN raw_assignments a
            ON a.source_assignment_id = s.source_assignment_id
        JOIN raw_classes c
            ON c.source_class_id = a.source_class_id
        JOIN raw_users student
            ON student.source_user_id = s.source_student_id
        JOIN raw_users teacher
            ON teacher.source_user_id = c.source_teacher_id
        LEFT JOIN raw_metrics m
            ON m.source_submission_id = s.source_submission_id
        ON CONFLICT (source_submission_id) DO UPDATE SET
            source_assignment_id = EXCLUDED.source_assignment_id,
            source_student_id = EXCLUDED.source_student_id,
            source_class_id = EXCLUDED.source_class_id,
            source_teacher_id = EXCLUDED.source_teacher_id,
            class_code = EXCLUDED.class_code,
            class_name = EXCLUDED.class_name,
            assignment_title = EXCLUDED.assignment_title,
            course_code = EXCLUDED.course_code,
            student_user_id_str = EXCLUDED.student_user_id_str,
            student_name = EXCLUDED.student_name,
            teacher_user_id_str = EXCLUDED.teacher_user_id_str,
            submitted_at = EXCLUDED.submitted_at,
            computed_at = EXCLUDED.computed_at,
            pi_score = EXCLUDED.pi_score,
            ui_score = EXCLUDED.ui_score,
            oi_score = EXCLUDED.oi_score,
            aic_score = EXCLUDED.aic_score,
            topic_score = EXCLUDED.topic_score,
            embedding_backend = EXCLUDED.embedding_backend,
            transformed_at = CURRENT_TIMESTAMP
        """,
    )

    execute(
        warehouse,
        """
        INSERT INTO mart_student_assignment_metrics (
            source_assignment_id,
            source_student_id,
            source_submission_id,
            source_class_id,
            class_code,
            class_name,
            assignment_title,
            course_code,
            student_user_id_str,
            student_name,
            submitted_at,
            computed_at,
            pi_score,
            ui_score,
            oi_score,
            aic_score,
            topic_score
        )
        SELECT
            source_assignment_id,
            source_student_id,
            source_submission_id,
            source_class_id,
            class_code,
            class_name,
            assignment_title,
            course_code,
            student_user_id_str,
            student_name,
            submitted_at,
            computed_at,
            pi_score,
            ui_score,
            oi_score,
            aic_score,
            topic_score
        FROM stg_submission_metrics
        ON CONFLICT (source_assignment_id, source_student_id) DO UPDATE SET
            source_submission_id = EXCLUDED.source_submission_id,
            source_class_id = EXCLUDED.source_class_id,
            class_code = EXCLUDED.class_code,
            class_name = EXCLUDED.class_name,
            assignment_title = EXCLUDED.assignment_title,
            course_code = EXCLUDED.course_code,
            student_user_id_str = EXCLUDED.student_user_id_str,
            student_name = EXCLUDED.student_name,
            submitted_at = EXCLUDED.submitted_at,
            computed_at = EXCLUDED.computed_at,
            pi_score = EXCLUDED.pi_score,
            ui_score = EXCLUDED.ui_score,
            oi_score = EXCLUDED.oi_score,
            aic_score = EXCLUDED.aic_score,
            topic_score = EXCLUDED.topic_score,
            refreshed_at = CURRENT_TIMESTAMP
        """,
    )

    execute(
        warehouse,
        """
        INSERT INTO mart_assignment_summary (
            source_assignment_id,
            source_class_id,
            class_code,
            class_name,
            assignment_title,
            course_code,
            submission_count,
            avg_pi_score,
            avg_ui_score,
            avg_oi_score,
            avg_aic_score,
            avg_topic_score,
            min_submitted_at,
            max_submitted_at
        )
        SELECT
            source_assignment_id,
            source_class_id,
            class_code,
            class_name,
            assignment_title,
            course_code,
            COUNT(*) AS submission_count,
            AVG(pi_score) AS avg_pi_score,
            AVG(ui_score) AS avg_ui_score,
            AVG(oi_score) AS avg_oi_score,
            AVG(aic_score) AS avg_aic_score,
            AVG(topic_score) AS avg_topic_score,
            MIN(submitted_at) AS min_submitted_at,
            MAX(submitted_at) AS max_submitted_at
        FROM stg_submission_metrics
        GROUP BY
            source_assignment_id,
            source_class_id,
            class_code,
            class_name,
            assignment_title,
            course_code
        ON CONFLICT (source_assignment_id) DO UPDATE SET
            source_class_id = EXCLUDED.source_class_id,
            class_code = EXCLUDED.class_code,
            class_name = EXCLUDED.class_name,
            assignment_title = EXCLUDED.assignment_title,
            course_code = EXCLUDED.course_code,
            submission_count = EXCLUDED.submission_count,
            avg_pi_score = EXCLUDED.avg_pi_score,
            avg_ui_score = EXCLUDED.avg_ui_score,
            avg_oi_score = EXCLUDED.avg_oi_score,
            avg_aic_score = EXCLUDED.avg_aic_score,
            avg_topic_score = EXCLUDED.avg_topic_score,
            min_submitted_at = EXCLUDED.min_submitted_at,
            max_submitted_at = EXCLUDED.max_submitted_at,
            refreshed_at = CURRENT_TIMESTAMP
        """,
    )

    execute(
        warehouse,
        """
        INSERT INTO mart_class_summary (
            source_class_id,
            class_code,
            class_name,
            source_teacher_id,
            teacher_user_id_str,
            assignment_count,
            submission_count,
            avg_pi_score,
            avg_ui_score,
            avg_oi_score,
            avg_aic_score,
            avg_topic_score
        )
        SELECT
            source_class_id,
            class_code,
            class_name,
            source_teacher_id,
            teacher_user_id_str,
            COUNT(DISTINCT source_assignment_id) AS assignment_count,
            COUNT(*) AS submission_count,
            AVG(pi_score) AS avg_pi_score,
            AVG(ui_score) AS avg_ui_score,
            AVG(oi_score) AS avg_oi_score,
            AVG(aic_score) AS avg_aic_score,
            AVG(topic_score) AS avg_topic_score
        FROM stg_submission_metrics
        GROUP BY
            source_class_id,
            class_code,
            class_name,
            source_teacher_id,
            teacher_user_id_str
        ON CONFLICT (source_class_id) DO UPDATE SET
            class_code = EXCLUDED.class_code,
            class_name = EXCLUDED.class_name,
            source_teacher_id = EXCLUDED.source_teacher_id,
            teacher_user_id_str = EXCLUDED.teacher_user_id_str,
            assignment_count = EXCLUDED.assignment_count,
            submission_count = EXCLUDED.submission_count,
            avg_pi_score = EXCLUDED.avg_pi_score,
            avg_ui_score = EXCLUDED.avg_ui_score,
            avg_oi_score = EXCLUDED.avg_oi_score,
            avg_aic_score = EXCLUDED.avg_aic_score,
            avg_topic_score = EXCLUDED.avg_topic_score,
            refreshed_at = CURRENT_TIMESTAMP
        """,
    )


def main() -> None:
    started_at = utc_now()
    raw_counts: dict[str, int] = {}
    report: ValidationReport | None = None
    history_recorded = False

    try:
        with closing(connect_source()) as source, closing(connect_warehouse()) as warehouse:
            create_schema(warehouse)
            raw_counts = load_raw(source, warehouse)
            transform(warehouse)

            report = collect_validation_report(source, warehouse)
            print(format_validation_report(report, raw_loaded_counts=raw_counts, title="ELT run summary"))

            if not report.passed:
                error_message = "ELT validation failed."
                insert_elt_run_history(
                    warehouse,
                    started_at=started_at,
                    status="failed",
                    raw_loaded_counts=raw_counts,
                    report=report,
                    error_message=error_message,
                )
                history_recorded = True
                warehouse.commit()
                raise RuntimeError(error_message)

            insert_elt_run_history(
                warehouse,
                started_at=started_at,
                status="success",
                raw_loaded_counts=raw_counts,
                report=report,
                error_message=None,
            )
            history_recorded = True
            warehouse.commit()
    except Exception as error:
        if not history_recorded:
            record_failed_run_history(
                started_at=started_at,
                raw_loaded_counts=raw_counts,
                report=report,
                error=error,
            )
        raise

    print("ELT completed successfully.")


if __name__ == "__main__":
    main()
