SET NAMES utf8mb4;

START TRANSACTION;

DELETE FROM benchmark_runs
WHERE run_id NOT IN (
  'BENCH-20260527-151525-e4eec79a',
  'BENCH-20260527-152044-37f01d75'
);

COMMIT;

SELECT run_id, label, status, total_items, processed_items, created_at
FROM benchmark_runs
ORDER BY created_at DESC;

SELECT COUNT(*) AS remaining_runs
FROM benchmark_runs;

SELECT COUNT(*) AS remaining_items
FROM benchmark_run_items;
