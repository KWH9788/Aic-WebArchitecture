# TODO

이 파일은 앞으로 진행할 프로젝트 작업을 기록합니다. 각 항목은 간결하고 실행 가능하게 작성하며, `AGENTS.md`의 서비스 경계와 운영 규칙을 따릅니다.

## 운영 규칙

- 의미 있는 변경을 시작하기 전에 작업 항목을 먼저 추가합니다.
- 한 행에는 하나의 작업만 기록하고, 담당 영역과 완료 기준을 명확히 적습니다.
- 완료된 작업은 이 파일에 남겨두지 않고 `LOG.md`로 옮깁니다.
- 코드 동작과 문서화된 규칙이 달라지면 관련 서비스 문서도 함께 갱신합니다.
- 비밀값, 실제 인증 정보, 로컬 `.env` 값, 비공개 배포 정보는 기록하지 않습니다.

## 상태 값

| 상태 | 의미 |
| --- | --- |
| `Backlog` | 아직 시작하지 않은 작업입니다. |
| `Ready` | 바로 시작할 수 있을 만큼 명확한 작업입니다. |
| `In Progress` | 현재 진행 중인 작업입니다. |
| `Blocked` | 결정, 의존성, 외부 이슈 때문에 대기 중인 작업입니다. |

## 우선순위 값

| 우선순위 | 의미 |
| --- | --- |
| `P0` | 긴급한 운영 영향 이슈 또는 릴리스 차단 작업입니다. |
| `P1` | 중요한 사용자 영향 작업 또는 여러 서비스에 걸친 작업입니다. |
| `P2` | 유용한 개선, 정리, 낮은 위험도의 수정 작업입니다. |
| `P3` | 나중에 검토할 아이디어 또는 선택적인 개선입니다. |

## 참고 기준

- 목표: 단건 `/analyze` 경로에서 `minmax_norm()`으로 PI/UI/OI/AIC가 0으로 붕괴하는 문제를 해결하고, 같은 정규화 기준으로 최적화 전후 benchmark를 비교합니다.
- 정규화 범위: batch CLI는 기존 min-max 정규화를 유지하고, 단건 `/analyze` 경로에만 saturating ratio 정규화를 적용합니다.
- saturating ratio 기본식: `normalized = value / (value + scale)`을 사용하고 결과를 0~1 범위로 유지합니다.
- saturating ratio scale 기본값: `pi_depth_tokens=100`, `pi_avg_sent_len_raw=20`, `pi_ttr_raw=0.5`, `ui_raw=0.2`, `oi_raw=0.125`로 시작합니다.
- `ui_raw`는 기존 `ui_distance * ui_newinfo_ratio * topic_score`를 사용한 뒤 saturating ratio로 정규화합니다.
- `oi_raw`는 기존 `(1 - topic_score) * topic_score`를 사용한 뒤 saturating ratio로 정규화합니다.
- 비교 원칙: 정규화 수정 효과와 SBERT 재로드 제거 효과를 분리해 측정합니다.
- benchmark label: baseline은 `baseline-normalized-no-sbert-cache`, optimized는 `optimized-normalized-sbert-cache`를 사용합니다.
- 완료 기준: baseline/optimized benchmark run이 모두 저장되고, compare에서 runtime은 크게 감소하며 `metric_snapshot` 점수 delta는 거의 없어야 합니다.

## 작업 목록

| 영역 | 우선순위 | 상태 | 작업 | 완료 기준 | 비고 |
| --- | --- | --- | --- | --- | --- |

## 결정된 방향

- TODO는 프로젝트 전체 작업 목록으로 관리합니다.
- 완료된 작업은 `LOG.md`에 기록하고 이 파일에서는 제거합니다.
- 단건 scoring 정규화 수정과 SBERT 재로드 제거 최적화는 benchmark 비교에서 서로 섞이지 않도록 단계별로 분리합니다.
- 단건 `/analyze`는 saturating ratio 정규화를 사용하고, batch CLI는 기존 min-max 정규화를 유지합니다.

## 열린 질문

- 현재 없음.
