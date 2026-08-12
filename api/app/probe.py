"""임베딩 조립안 비교 API — chroma 컬렉션 두 개를 나란히 질의한다.

`scripts/embed_probe.py`가 뽑은 벡터를 `scripts/load_chroma.py`가 chroma로
옮겨 둔 상태를 전제한다. 여기서는 임베딩도 적재도 하지 않고 **질의만** 한다.

  foods_name      A 조립안 (식품명만)
  foods_name_cat  C 조립안 (식품명 + 대/중/소분류)

질의 임베딩은 한 번만 하고 양쪽에 같은 벡터를 쓴다. 그래야 결과 차이를
조립안 탓이라고 말할 수 있다.

이 라우터는 시연 흐름(v0.1 → v1.0)의 일부가 아니라 실험 도구다.
"""

import os
from functools import lru_cache

import numpy as np
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/probe", tags=["probe"])

DIM = int(os.environ.get("EMBEDDING_DIM", "768"))
MODEL = os.environ.get("EMBEDDING_MODEL", "gemini/gemini-embedding-001")
CHROMA_HOST = os.environ.get("CHROMA_HOST", "chroma")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8000"))

MODES = {
    "name": {"collection": "foods_name", "tag": "A", "label": "식품명만"},
    "name_cat": {"collection": "foods_name_cat", "tag": "C", "label": "식품명 + 대/중/소분류"},
}


@lru_cache(maxsize=1)
def client():
    import chromadb

    return chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)


def collection(mode: str):
    if mode not in MODES:
        raise HTTPException(400, f"mode는 {list(MODES)} 중 하나")
    try:
        return client().get_collection(MODES[mode]["collection"])
    except Exception as exc:  # noqa: BLE001 — 컬렉션이 없으면 만드는 법을 알려준다
        raise HTTPException(
            503,
            f"컬렉션 {MODES[mode]['collection']} 없음. "
            "릴리즈의 chroma_foods.tar.gz 를 data/dist/ 에 두고 compose를 다시 올리거나, "
            "docker compose run --rm index-load 로 직접 적재하세요",
        ) from exc


def embed_query(q: str) -> list[float]:
    """질의를 벡터로. 인덱스가 배포돼 있어도 **이 한 번은 API를 부른다.**

    색인은 받아 쓸 수 있지만 질의는 그때그때 임베딩해야 한다. 질의 한 건이라
    사실상 공짜지만, 키가 없으면 여기서 막힌다. 학생이 가장 자주 밟는 자리라
    "왜 안 되는지"를 분명히 말해야 한다.
    """
    import litellm

    try:
        res = litellm.embedding(
            model=MODEL, input=[q], dimensions=DIM, task_type="RETRIEVAL_QUERY"
        )
    except Exception as exc:  # noqa: BLE001
        name = type(exc).__name__
        if "auth" in name.lower() or "AuthenticationError" in name or not os.environ.get(
            "GEMINI_API_KEY", ""
        ):
            raise HTTPException(
                503,
                "질의를 임베딩할 수 없습니다. 인덱스는 받아 쓸 수 있어도 "
                "질의 임베딩에는 키가 필요합니다. `cp .env.example .env` 후 "
                "GEMINI_API_KEY를 채우고 `docker compose up -d --force-recreate api` 하세요",
            ) from exc
        raise HTTPException(503, f"임베딩 호출 실패({name}): {str(exc)[:200]}") from exc

    v = np.array(res.data[0]["embedding"], dtype=np.float32)
    # 축소된 벡터는 norm이 1이 아니다. 색인 쪽도 정규화해 넣었으므로 질의도 맞춘다
    return (v / max(float(np.linalg.norm(v)), 1e-9)).tolist()


def search(mode: str, qvec: list[float], limit: int) -> list[dict]:
    res = collection(mode).query(
        query_embeddings=[qvec],
        n_results=limit,
        include=["documents", "metadatas", "distances"],
    )
    items = []
    for doc, meta, dist in zip(
        res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        # chroma의 cosine space는 거리(1 - 유사도)를 준다. 유사도로 되돌린다
        items.append({
            "score": round(1.0 - float(dist), 4),
            "code": meta.get("code", ""),
            "name": meta.get("name", ""),
            "category_big": meta.get("category_big", ""),
            "category_mid": meta.get("category_mid", ""),
            "category_small": meta.get("category_small", ""),
            "maker": meta.get("maker", ""),
            "embedded_text": doc,
        })
    return items


@router.get("/modes")
def list_modes() -> dict:
    """어떤 조립안이 준비돼 있는지. UI가 선택지를 그리는 근거."""
    out, rows = [], 0
    for mode, meta in MODES.items():
        try:
            count = client().get_collection(meta["collection"]).count()
        except Exception:  # noqa: BLE001
            count = 0
        rows = max(rows, count)
        out.append({
            "mode": mode,
            "tag": meta["tag"],
            "label": meta["label"],
            "collection": meta["collection"],
            "ready": count > 0,
            "count": count,
        })
    return {"modes": out, "rows": rows, "dim": DIM, "store": f"chroma://{CHROMA_HOST}"}


@router.get("/semantic")
def semantic(
    q: str = Query(..., min_length=1),
    mode: str = Query("name_cat"),
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    return {"q": q, "mode": mode, "items": search(mode, embed_query(q), limit)}


@router.get("/compare")
def compare(q: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=50)) -> dict:
    """같은 질의를 두 조립안에 동시에 던진다."""
    qvec = embed_query(q)
    results = {}
    for mode in MODES:
        try:
            results[mode] = search(mode, qvec, limit)
        except HTTPException as exc:
            results[mode] = {"error": exc.detail}
    return {"q": q, "results": results}
