"""관문 테스트 — db가 없어도 서비스는 뜬다.

CI에는 PostgreSQL도, LLM 키도, 187MB 원본도 없다. 그 조건에서 도는 것만
여기 둔다. **테스트가 도는 조건을 좁게 잡는 것도 설계다.**

그리고 그 조건이 곧 v0.1의 조건이다. `/foods`는 db가 없을 때 v0.1과 같은
모양으로 답해야 하고, 그래야 UI가 코드 한 줄 안 바꾸고 계속 돈다. 이 파일이
그 계약을 지킨다.
"""

from fastapi.testclient import TestClient

from app import foods
from app.main import app

client = TestClient(app)


def test_health_ok():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_foods_degrades_to_empty_state_without_db(monkeypatch):
    """db가 없는 것은 오류가 아니라 아직 그 회전이 안 온 것이다.

    500도 503도 아닌 200과 빈 목록으로 답해야 한다. UI는 이 응답 하나로
    "데이터가 있나"를 판단하므로, 여기서 예외가 나면 화면이 통째로 죽는다.

    db를 **명시적으로 끊고** 검사한다. 그냥 호출하면 CI에서는 통과하고
    개발 환경에서는 실패한다. 환경에 따라 결과가 갈리는 것은 테스트가 아니다.
    """
    monkeypatch.setattr(foods, "DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")
    body = client.get("/foods").json()
    assert body["total"] == 0
    assert body["items"] == []
    assert "message" in body


def test_foods_always_reports_pipeline_stages():
    """진행 막대의 근거. 데이터가 있든 없든 같은 자리에서 나와야 한다."""
    stages = {s["stage"] for s in client.get("/foods").json()["pipeline"]}
    assert stages == {"raw", "clean", "parsed"}


def test_status_endpoint_matches():
    """/status는 같은 값을 따로도 준다. UI 말고 다른 소비자를 위한 자리."""
    assert client.get("/status").json()["pipeline"] == client.get("/foods").json()["pipeline"]


def test_sort_whitelist_rejects_unknown():
    """정렬은 SQL에 이어 붙는 자리라 화이트리스트 밖은 400으로 막는다."""
    assert client.get("/foods", params={"sort": "sodium_asc; drop table foods"}).status_code == 400
