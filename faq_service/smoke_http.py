"""Run after FastAPI starts: python -m faq_service.smoke_http"""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

BASE = os.getenv("FAQ_SMOKE_URL", "http://127.0.0.1:8011").rstrip("/")
CASES = json.loads((Path(__file__).with_name("smoke_questions.json")).read_text(encoding="utf-8"))

health = httpx.get(f"{BASE}/health", timeout=10).json()
print("HEALTH", health)
if health.get("status") != "ok":
    raise SystemExit("FAQ service is not healthy")

failed = 0
for case in CASES:
    r = httpx.post(f"{BASE}/chat", json={"message": case["q"], "top_k": 4, "history": []}, timeout=90)
    r.raise_for_status()
    data = r.json()
    answer = data.get("answer", "")
    low = answer.lower()
    ok = True
    for needle in case.get("expect", []):
        ok = ok and needle.lower() in low
    if case.get("expect_any"):
        ok = ok and any(x.lower() in low for x in case["expect_any"])
    if case.get("refusal"):
        ok = ok and data.get("mode") == "refusal"
    print(("OK" if ok else "FAIL"), case["q"], "=>", answer[:180], "|", data.get("mode"))
    failed += 0 if ok else 1

# Memory pair
history = []
first = "Расскажи про бота для записи клиентов"
r = httpx.post(f"{BASE}/chat", json={"message": first, "history": history}, timeout=90).json()
history += [{"role": "user", "content": first}, {"role": "assistant", "content": r.get("answer", "")}]
second = "А сколько это будет стоить?"
r2 = httpx.post(f"{BASE}/chat", json={"message": second, "history": history}, timeout=90).json()
ok = "15 000" in r2.get("answer", "")
print(("OK" if ok else "FAIL"), "MEMORY bot -> price =>", r2.get("answer", "")[:180])
failed += 0 if ok else 1

print(f"TOTAL FAILED: {failed}")
raise SystemExit(1 if failed else 0)
