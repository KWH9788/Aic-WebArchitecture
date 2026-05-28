# DB ERD

이 문서는 AIC Web backend가 사용하는 운영 MySQL schema의 핵심 엔티티와 관계를 요약합니다. 기준 소스는 `init.sql`과 `aic-backend/app/models/db_models.py`입니다.

## Entity Relationship Diagram

```mermaid
erDiagram
    USERS {
        int id PK
        string user_id_str UK
        string password_hash
        enum role
        string name
        string email
        datetime created_at
        datetime updated_at
    }

    CLASSES {
        int id PK
        string class_code UK
        string class_name
        int teacher_id FK
        string semester
        datetime created_at
    }

    CLASS_ENROLLMENTS {
        int id PK
        int class_id FK
        int student_id FK
        datetime enrolled_at
    }

    ASSIGNMENTS {
        int id PK
        int class_id FK
        string title
        text description
        string course_code
        datetime due_date
        datetime created_at
    }

    SUBMISSIONS {
        int id PK
        int assignment_id FK
        int student_id FK
        text chatgpt_before
        text user_prompt
        text essay
        datetime submitted_at
    }

    METRICS {
        int id PK
        int submission_id FK_UK
        int pi_score
        int ui_score
        int oi_score
        int aic_score
        string embedding_backend
        datetime computed_at
    }

    ANALYSIS_JOBS {
        int id PK
        string job_uuid UK
        int submission_id FK
        enum status
        text error_message
        datetime created_at
        datetime started_at
        datetime completed_at
    }

    ANALYSIS_RUNS {
        int id PK
        string run_id UK
        string job_uuid UK
        int submission_id FK
        enum status
        int processed_rows
        json data_health
        json backend_info
        json pipeline_steps
        datetime created_at
        datetime completed_at
    }

    BENCHMARK_RUNS {
        int id PK
        string run_id UK
        string label
        enum status
        json dataset_snapshot
        string dataset_hash
        int total_items
        int processed_items
        float avg_runtime_sec
        json stage_runtime_totals
        datetime created_at
        datetime completed_at
    }

    BENCHMARK_RUN_ITEMS {
        int id PK
        int benchmark_run_id FK
        int submission_id FK
        int sample_index
        bool is_warmup
        enum status
        json metric_snapshot
        float runtime_sec
        string embedding_backend
        json pipeline_steps
    }

    TEACHER_FEEDBACK {
        int id PK
        int assignment_id FK
        int student_id FK
        int teacher_id FK
        text content
        datetime created_at
        datetime updated_at
    }

    USERS ||--o{ CLASSES : teaches
    USERS ||--o{ CLASS_ENROLLMENTS : enrolls
    CLASSES ||--o{ CLASS_ENROLLMENTS : has
    CLASSES ||--o{ ASSIGNMENTS : contains
    ASSIGNMENTS ||--o{ SUBMISSIONS : receives
    USERS ||--o{ SUBMISSIONS : submits
    SUBMISSIONS ||--|| METRICS : has
    SUBMISSIONS ||--o{ ANALYSIS_JOBS : queued_as
    SUBMISSIONS |o--o{ ANALYSIS_RUNS : measured_by
    BENCHMARK_RUNS ||--o{ BENCHMARK_RUN_ITEMS : contains
    SUBMISSIONS |o--o{ BENCHMARK_RUN_ITEMS : sampled_as
    ASSIGNMENTS ||--o{ TEACHER_FEEDBACK : feedback_for
    USERS ||--o{ TEACHER_FEEDBACK : receives_feedback
    USERS ||--o{ TEACHER_FEEDBACK : gives_feedback
```

## 관계 요약

| 관계 | 의미 |
| --- | --- |
| `users` -> `classes` | 교사 사용자가 여러 수업을 담당할 수 있습니다. |
| `classes` -> `class_enrollments` <- `users` | 학생과 수업의 N:M 관계를 enrollment 테이블로 표현합니다. |
| `classes` -> `assignments` | 한 수업은 여러 과제를 가집니다. |
| `assignments` -> `submissions` <- `users` | 학생은 과제별로 하나의 제출물을 가질 수 있습니다. `uq_submission`이 중복 제출을 막습니다. |
| `submissions` -> `metrics` | 제출물 하나당 최신 metric row 하나를 저장합니다. |
| `submissions` -> `analysis_jobs` | 제출 분석 요청의 비동기 job 상태를 저장합니다. |
| `submissions` -> `analysis_runs` | 관리자 분석 품질 모니터용 실행 측정 snapshot을 저장합니다. |
| `benchmark_runs` -> `benchmark_run_items` -> `submissions` | benchmark 실행 하나가 여러 제출 sample을 재분석하고 item별 metric/runtime snapshot을 저장합니다. |
| `teacher_feedback` | 교사, 학생, 과제 조합의 피드백을 저장합니다. `uq_feedback`이 과제-학생당 피드백 중복을 막습니다. |

## 주요 제약

- `users.user_id_str`, `classes.class_code`, `analysis_jobs.job_uuid`, `analysis_runs.run_id`, `benchmark_runs.run_id`는 unique입니다.
- `class_enrollments`는 `(class_id, student_id)` unique입니다.
- `submissions`는 `(assignment_id, student_id)` unique입니다.
- `metrics.submission_id`는 unique라 제출물과 1:1 관계입니다.
- `benchmark_run_items`는 `(benchmark_run_id, sample_index)`와 `(benchmark_run_id, submission_id)` unique입니다.
- `teacher_feedback`은 `(assignment_id, student_id)` unique입니다.
