import json
import urllib.request

base = "http://localhost:8000/api/v1"
login_payload = json.dumps({
    "user_id": "admin",
    "password": "admin1234",
    "role": "admin",
}).encode()

login_request = urllib.request.Request(
    f"{base}/auth/login",
    data=login_payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)

with urllib.request.urlopen(login_request, timeout=20) as response:
    token = json.loads(response.read().decode())["access_token"]

compare_url = (
    f"{base}/admin/benchmarks/compare"
    "?baselineRunId=BENCH-20260527-151525-e4eec79a"
    "&optimizedRunId=BENCH-20260527-152044-37f01d75"
)
compare_request = urllib.request.Request(
    compare_url,
    headers={"Authorization": f"Bearer {token}"},
)

with urllib.request.urlopen(compare_request, timeout=20) as response:
    data = json.loads(response.read().decode())

print(json.dumps({
    "same_dataset": data["same_dataset"],
    "avg_runtime": data["runtime"]["avg"],
    "score_delta_aic": data.get("score_delta", {}).get("metrics", {}).get("aic"),
}, ensure_ascii=False, indent=2))
