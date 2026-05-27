SET NAMES utf8mb4;

SELECT run_id, label, status, total_items, processed_items, created_at
FROM benchmark_runs
ORDER BY created_at DESC;

SELECT COUNT(*) AS runs_to_delete
FROM benchmark_runs
WHERE run_id NOT IN (
  'BENCH-20260527-151525-e4eec79a',
  'BENCH-20260527-152044-37f01d75'
);

SELECT COUNT(*) AS items_to_delete
FROM benchmark_run_items
WHERE benchmark_run_id IN (
  SELECT id
  FROM benchmark_runs
  WHERE run_id NOT IN (
    'BENCH-20260527-151525-e4eec79a',
    'BENCH-20260527-152044-37f01d75'
  )
);
