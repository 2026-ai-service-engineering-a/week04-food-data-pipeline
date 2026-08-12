"""가공식품 영양 탐색기 API — v0.1: 데이터가 아직 없는 뼈대.

이 저장소의 주인공은 API가 아니라 **데이터**다. 그래서 v0.1의 API는
"데이터가 없다"고 정직하게 말하는 것이 일이다. 회전이 돌면서 채워진다.

  1회전 feature/clean       정제 + 섭취참고량 파싱 (pipeline/clean.py, serving.py)
  2회전 feature/pg-service  PostgreSQL 적재 + GET /foods, GET /foods/{code}  ← 지금 여기
  3회전 feature/rag-search  Chroma 인덱스 + GET /foods/semantic, POST /ask

헤드리스 구조: 이 API는 UI를 모른다. curl·Swagger(/docs)로 불러도 똑같이 동작한다.
"""

from fastapi import FastAPI

from app.foods import router as foods_router
from app.status import pipeline_status

app = FastAPI(title="가공식품 영양 탐색기 API", version="0.1.0")

@app.get("/health")
def health() -> dict:
    """데이터가 없어도 /health는 뜬다 — 서비스 기동과 데이터 준비는 다른 문제다."""
    return {"status": "ok", "version": app.version}


@app.get("/status")
def status() -> dict:
    """파이프라인이 어디까지 왔나. /foods 응답에도 같은 값이 실린다."""
    return {"pipeline": pipeline_status()}


# 2회전이 /foods를 PostgreSQL 검색으로 교체한다. db가 없거나 표가 비었으면
# v0.1과 같은 모양(total 0 · message · pipeline)으로 답하므로 UI는 안 바뀐다
app.include_router(foods_router)
