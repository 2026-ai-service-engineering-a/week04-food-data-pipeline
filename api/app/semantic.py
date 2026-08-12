"""의미 검색 — 글자가 아니라 뜻으로 찾는다. **LLM은 안 부른다.**

2회전의 `/foods`가 못 한 것이 여기서 된다. "매콤한 분식 간식"은 SQL에서 0건이다.
그 문자열이 든 식품명이 없기 때문이고, SQL은 틀리지 않았다. 글자만 봤을 뿐이다.

챗봇으로 풀고 싶은 문제의 절반은 검색으로 끝난다. 이 파일이 그 절반이다.

벡터 DB는 색인이고 원본은 PostgreSQL 한 곳이다. chroma는 "어느 식품코드가
가까운가"까지만 답하고, 화면에 쓸 값은 그 코드로 원본에서 꺼낸다. **원본을 두
곳에 두면 언젠가 둘이 어긋난다.**
"""

import os
from functools import lru_cache

import psycopg
from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from app.foods import DATABASE_URL, empty_state

router = APIRouter(tags=["semantic"])

CHROMA_HOST = os.environ.get("CHROMA_HOST", "chroma")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8000"))
MODEL = os.environ.get("EMBEDDING_MODEL", "gemini/gemini-embedding-001")
DIM = int(os.environ.get("EMBEDDING_DIM", "768"))
COLLECTION = "foods_name_cat"


@lru_cache(maxsize=1)
def client():
    import chromadb

    return chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)


def collection():
    return client().get_collection(COLLECTION)


def embed_query(q: str) -> list[float]:
    """질의를 벡터로. **인덱스를 받아 썼어도 이 한 번은 API를 부른다.**

    색인은 배포할 수 있지만 질의는 그때그때 임베딩해야 한다. 질의 한 건이라
    사실상 공짜인데, 키가 없으면 여기서 막힌다. 학생이 가장 자주 밟는 자리라
    "왜 안 되는지"를 분명히 말해야 한다.

    task_type이 색인 때와 다르다. 이 모델은 색인용과 질의용 임베딩을 나눈다.
    """
    import litellm

    res = litellm.embedding(model=MODEL, input=[q], dimensions=DIM,
                            task_type="RETRIEVAL_QUERY")
    vec = res.data[0]["embedding"]
    norm = sum(x * x for x in vec) ** 0.5
    return [x / norm for x in vec] if norm else vec


def hydrate(codes: list[str]) -> dict[str, dict]:
    """식품코드로 원본 행을 꺼낸다. 벡터 DB가 아니라 여기가 진실이다."""
    if not codes:
        return {}
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select code, name, category_big, category_mid, maker,"
                " energy_kcal, sodium_mg, sugar_g, serving_g, parse_method"
                " from foods where code = any(%(codes)s)", {"codes": codes})
            return {r["code"]: r for r in cur.fetchall()}


def search(q: str, limit: int, sodium_max: float | None = None) -> list[dict]:
    where = {"sodium_mg": {"$lte": sodium_max}} if sodium_max is not None else None
    res = collection().query(
        query_embeddings=[embed_query(q)],
        n_results=limit,
        where=where,
    )
    codes = res["ids"][0]
    rows = hydrate(codes)
    items = []
    for code, dist in zip(codes, res["distances"][0]):
        row = rows.get(code)
        if row is None:
            # 색인에는 있는데 원본에 없다. 인덱스가 원본보다 오래됐다는 뜻이라
            # 조용히 빠뜨리지 않고 남긴다
            items.append({"code": code, "name": None, "score": round(1 - dist, 4),
                          "note": "원본에 없는 코드 — 인덱스가 오래됐습니다"})
            continue
        items.append({**row, "score": round(1 - dist, 4)})
    return items


@router.get("/foods/semantic")
def semantic(
    q: str = Query(..., description="자연어 질의"),
    limit: int = Query(10, ge=1, le=50),
    sodium_max: float | None = Query(None, description="나트륨 상한 (메타데이터 필터)"),
) -> dict:
    """의미로 찾는다. 없으면 없다고 답하되 500으로 죽지는 않는다."""
    try:
        items = search(q, limit, sodium_max)
    except Exception as exc:  # noqa: BLE001 — 컬렉션 부재·키 부재·연결 실패가 다 여기다
        return {**empty_state(_why(exc)), "q": q}
    return {"q": q, "total": len(items), "items": items}


def _why(exc: Exception) -> str:
    """왜 안 되는지를 말한다. 학생이 가장 자주 밟는 세 자리를 갈라 준다."""
    text = str(exc)
    if "api_key" in text.lower() or "API key" in text:
        return "임베딩 키가 없습니다. .env의 GEMINI_API_KEY를 확인하세요 (질의 임베딩은 매번 필요합니다)"
    if COLLECTION in text or "does not exist" in text or "not found" in text.lower():
        return ("벡터 인덱스가 아직 없습니다. 릴리즈의 chroma_foods.tar.gz를 data/dist/에 두고 "
                "compose를 다시 올리거나, docker compose run --rm index-load로 직접 만드세요")
    return f"의미 검색을 할 수 없습니다: {exc}"
