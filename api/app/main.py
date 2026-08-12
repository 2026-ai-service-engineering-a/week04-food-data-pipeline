"""가공식품 영양 탐색기 API — v0.1: 데이터가 아직 없는 뼈대.

이 저장소의 주인공은 API가 아니라 **데이터**다. 그래서 v0.1의 API는
"데이터가 없다"고 정직하게 말하는 것이 일이다. 회전이 돌면서 채워진다.

  1회전 feature/clean       정제 + 섭취참고량 파싱 (pipeline/clean.py, serving.py)
  2회전 feature/pg-service  PostgreSQL 적재 + GET /foods, GET /foods/{code}
  3회전 feature/rag-search  Chroma 인덱스 + GET /foods/semantic, POST /ask  ← 지금 여기

헤드리스 구조: 이 API는 UI를 모른다. curl·Swagger(/docs)로 불러도 똑같이 동작한다.
"""

from fastapi import FastAPI

from app.ask import router as ask_router
from app.foods import router as foods_router
from app.probe import router as probe_router
from app.semantic import router as semantic_router
from app.status import pipeline_status

app = FastAPI(title="가공식품 영양 탐색기 API", version="1.0.0")

@app.get("/health")
def health() -> dict:
    """데이터가 없어도 /health는 뜬다 — 서비스 기동과 데이터 준비는 다른 문제다."""
    return {"status": "ok", "version": app.version}


@app.get("/status")
def status() -> dict:
    """파이프라인이 어디까지 왔나. /foods 응답에도 같은 값이 실린다."""
    return {"pipeline": pipeline_status()}


# 3회전이 더하는 두 층. 의미 검색은 LLM 없이 임베딩만으로 돌고,
# /ask만 LLM을 부른다 — 그것도 검색이 추린 다섯 건을 들고서다.
#
# **등록 순서가 중요하다.** FastAPI는 먼저 등록된 경로부터 맞춰 본다.
# foods_router의 /foods/{code}를 먼저 붙이면 /foods/semantic 요청이
# code="semantic"으로 잡혀 404가 난다. 구체적인 경로가 먼저다.
app.include_router(semantic_router)
app.include_router(ask_router)

# 2회전이 /foods를 PostgreSQL 검색으로 교체한다. db가 없거나 표가 비었으면
# v0.1과 같은 모양(total 0 · message · pipeline)으로 답하므로 UI는 안 바뀐다
app.include_router(foods_router)

# 임베딩 조립안 비교 도구. 시연 흐름의 일부가 아니라 6-1절 실험을 재현하는
# 대조군이라, 배포 인덱스에 비교용 컬렉션이 있을 때만 쓸모가 있다
app.include_router(probe_router)
