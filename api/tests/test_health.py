"""v0.1 관문 테스트 — 데이터가 없어도 서비스는 뜬다.

CI에는 LLM 키도 원본 데이터도 없다. 그 조건에서 도는 것만 여기 둔다.
회전이 돌면 정제 순수 함수(1회전)·규칙 파서(2회전) 테스트가 옆에 쌓인다.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_foods_reports_empty_state():
    """데이터가 없을 때 500이 아니라 0건과 안내를 준다 — 빈 상태도 정상 응답이다."""
    res = client.get("/foods")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 0
    assert body["items"] == []
    assert "데이터" in body["message"]


def test_foods_reports_pipeline_stages():
    """UI 빈 상태 화면이 "어디까지 왔는지"를 그리는 근거."""
    stages = {s["stage"] for s in client.get("/foods").json()["pipeline"]}
    assert stages == {"raw", "clean", "parsed"}
