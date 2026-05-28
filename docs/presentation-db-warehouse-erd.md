# Presentation DB & Warehouse ERD

발표에서 한눈에 설명하기 위한 요약형 ERD입니다. 세부 컬럼 전체보다 데이터 흐름과 핵심 관계를 우선합니다.

## 발표용 핵심 메시지

- 운영 DB는 수업, 학생, 과제, 제출, AIC metric을 저장합니다.
- backend는 제출 분석 job을 만들고 pipeline 결과를 `metrics`에 저장합니다.
- ELT는 운영 DB의 핵심 5개 테이블을 warehouse raw layer로 복제합니다.
- warehouse는 raw 데이터를 `stg_submission_metrics`로 결합한 뒤 학생/과제, 과제, 수업 단위 mart를 만듭니다.
- `elt_run_history`는 적재 성공/실패와 검증 상태를 기록합니다.

## Mermaid Overview

```mermaid
flowchart LR
    subgraph operational["Operational MySQL: aic_db"]
        users["users\nPK id\nrole, name"]
        classes["classes\nPK id\nFK teacher_id"]
        enrollments["class_enrollments\nstudent-class bridge"]
        assignments["assignments\nFK class_id"]
        submissions["submissions\nFK assignment_id\nFK student_id"]
        metrics["metrics\n1:1 submission\nPI/UI/OI/AIC"]
        ops_support["analysis_jobs\nanalysis_runs\nteacher_feedback\nbenchmark_*"]

        users --> classes
        users --> enrollments
        classes --> enrollments
        classes --> assignments
        assignments --> submissions
        users --> submissions
        submissions --> metrics
        submissions --> ops_support
    end

    subgraph elt["ELT"]
        extract["docker compose run --rm elt"]
    end

    subgraph warehouse["PostgreSQL Warehouse: aic_warehouse"]
        raw["RAW layer\nraw_users\nraw_classes\nraw_assignments\nraw_submissions\nraw_metrics"]
        stg["STAGING\nstg_submission_metrics\njoined submission + scores"]
        mart_student["MART\nmart_student_assignment_metrics"]
        mart_assignment["MART\nmart_assignment_summary"]
        mart_class["MART\nmart_class_summary"]
        history["elt_run_history\nstatus, counts, validation"]

        raw --> stg
        stg --> mart_student
        stg --> mart_assignment
        stg --> mart_class
        extract --> history
    end

    metrics --> extract
    submissions --> extract
    assignments --> extract
    classes --> extract
    users --> extract
    extract --> raw
```

이미지 파일: `docs/presentation-db-warehouse-erd.svg`
