"""Disposable current-backend account; keep credentials in ignored local JSON only."""
import json
import time
import uuid
from pathlib import Path

import requests

base = Path(__file__).resolve().parent
path = base / "backend-local-secrets.json"
credentials = json.loads(path.read_text(encoding="utf-8"))
url = "http://127.0.0.1:19082"
for attempt in range(60):
    try:
        requests.get(url + "/actuator/health", timeout=2)
        break
    except requests.ConnectionError:
        time.sleep(1)
else:
    raise RuntimeError("Current backend did not start")
email = "current-verification-" + uuid.uuid4().hex[:12] + "@gmail.com"
session = requests.Session()
response = session.post(url + "/api/v1/auth/signup", json={
    "email": email, "password": credentials["password"], "nickname": "Local verification"}, timeout=10)
response.raise_for_status()
response = session.post(url + "/api/v1/auth/login", json={
    "email": email, "password": credentials["password"]}, timeout=10)
response.raise_for_status()
credentials.update(access_token=response.json()["access_token"], email=email)
path.write_text(json.dumps(credentials), encoding="utf-8")
session.headers["Authorization"] = "Bearer " + credentials["access_token"]
results = {"signup_login": "passed"}
for endpoint in ("/api/v1/glossary", "/api/v1/transcript/glossary"):
    response = session.get(url + endpoint, timeout=20)
    response.raise_for_status()
    results[endpoint] = {"status": response.status_code, "terms": len(response.json()["terms"])}
(base / "backend-runtime-auth-result.json").write_text(json.dumps(results), encoding="utf-8")
print(json.dumps(results))
