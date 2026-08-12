"""임베딩 조립안 비교 API — 프로브가 만든 벡터를 그대로 검색에 쓴다.

`scripts/embed_probe.py`가 남긴 `data/clean/.probe_*.f32`를 읽어 의미 검색을
제공한다. 조립안을 골라 같은 질의를 던져 볼 수 있고, 그 차이를 눈으로 본다.

**벡터 DB가 없다.** 30만 x 768 코사인이 numpy로 0.6초라, 이 규모·이 용도에는
memmap 하나면 충분하다. 벡터 DB가 필요해지는 지점은 따로 있다 — 영속적인
운영 서비스, 메타데이터 필터, 여러 프로세스의 동시 접근, 증분 갱신.
3회전이 chroma 서비스를 세우는 이유가 그것이고, 이 파일은 그 전에
"왜 굳이 DB가 필요한가"를 묻게 만드는 대조군이다.

이 라우터는 시연 흐름(v0.1 → v1.0)의 일부가 아니라 실험 도구다.
"""

import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/probe", tags=["probe"])

DATA = Path(os.environ.get("DATA_DIR", "data")) / "clean"
SOURCE = DATA / ".probe_source.parquet"
DIM = int(os.environ.get("EMBEDDING_DIM", "768"))
MODEL = os.environ.get("EMBEDDING_MODEL", "gemini/gemini-embedding-001")

EMPTY_CATEGORY = {"해당없음", "", "nan", "None"}

MODES = {
    "name": {"tag": "A", "label": "식품명만"},
    "name_cat": {"tag": "C", "label": "식품명 + 대/중/소분류"},
}


def build_text(row, mode: str) -> str:
    if mode == "name":
        return str(row["식품명"])
    cats = [str(row[c]) for c in ("식품대분류명", "식품중분류명", "식품소분류명")]
    return " · ".join([str(row["식품명"])] + [c for c in cats if c not in EMPTY_CATEGORY])


@lru_cache(maxsize=1)
def source() -> pd.DataFrame:
    if not SOURCE.exists():
        raise HTTPException(503, f"{SOURCE} 없음 — scripts/embed_probe.py를 먼저 돌리세요")
    return pd.read_parquet(SOURCE).fillna("")


@lru_cache(maxsize=4)
def index_for(mode: str):
    """(벡터 memmap, 고유값 인덱스 → 대표 행 번호)를 만든다.

    행 → 고유값 매핑은 np.unique로 다시 계산한다. 30만 건에 0.7초라
    저장할 이유가 없고, 임베딩할 때와 같은 순서가 나온다는 보장이 덤이다.
    """
    if mode not in MODES:
        raise HTTPException(400, f"mode는 {list(MODES)} 중 하나")
    tag = MODES[mode]["tag"]
    vec = DATA / f".probe_{tag}.f32"
    if not vec.exists():
        raise HTTPException(503, f"{vec} 없음 — 이 조립안은 아직 임베딩되지 않았습니다")

    df = source()
    texts = np.array([build_text(r, mode) for _, r in df.iterrows()], dtype=object)
    uniq, inverse = np.unique(texts, return_inverse=True)
    mat = np.memmap(vec, dtype=np.float32, mode="r", shape=(len(uniq), DIM))

    first_row = np.full(len(uniq), -1, dtype=np.int64)
    for row_i, u_i in enumerate(inverse):
        if first_row[u_i] < 0:
            first_row[u_i] = row_i
    return mat, first_row


def embed_query(q: str) -> np.ndarray:
    import litellm

    res = litellm.embedding(
        model=MODEL, input=[q], dimensions=DIM, task_type="RETRIEVAL_QUERY"
    )
    v = np.array(res.data[0]["embedding"], dtype=np.float32)
    return v / max(float(np.linalg.norm(v)), 1e-9)


def search(mode: str, qvec: np.ndarray, limit: int, chunk: int = 50000) -> list[dict]:
    mat, first_row = index_for(mode)
    df = source()
    n = mat.shape[0]
    pool: list[tuple[float, int]] = []
    for s in range(0, n, chunk):
        # memmap 슬라이스는 읽기 전용 뷰라 제자리 연산이 막힌다. np.array로 복사한다
        block = np.array(mat[s : s + chunk], dtype=np.float32)
        # 잘린 벡터는 norm이 1이 아니다. 정규화 없이 코사인을 재면 안 된다
        block /= np.clip(np.linalg.norm(block, axis=1, keepdims=True), 1e-9, None)
        sims = block @ qvec
        take = min(limit, sims.shape[0])
        loc = np.argpartition(-sims, take - 1)[:take]
        pool.extend(zip(sims[loc].tolist(), (loc + s).tolist()))
    pool.sort(key=lambda x: -x[0])

    items = []
    for score, u_i in pool[:limit]:
        row = df.iloc[int(first_row[u_i])]
        items.append({
            "score": round(float(score), 4),
            "code": row["식품코드"],
            "name": row["식품명"],
            "category_big": row["식품대분류명"],
            "category_mid": row["식품중분류명"],
            "category_small": row["식품소분류명"],
            "maker": row["제조사명"],
            "embedded_text": build_text(row, mode),
        })
    return items


@router.get("/modes")
def list_modes() -> dict:
    """어떤 조립안이 준비돼 있는지. UI가 선택지를 그리는 근거."""
    out = []
    for mode, meta in MODES.items():
        vec = DATA / f".probe_{meta['tag']}.f32"
        out.append({
            "mode": mode,
            "tag": meta["tag"],
            "label": meta["label"],
            "ready": vec.exists(),
            "size_mb": round(vec.stat().st_size / 1024 / 1024) if vec.exists() else 0,
        })
    return {"modes": out, "rows": len(source()) if SOURCE.exists() else 0, "dim": DIM}


@router.get("/semantic")
def semantic(
    q: str = Query(..., min_length=1),
    mode: str = Query("name_cat"),
    limit: int = Query(10, ge=1, le=50),
) -> dict:
    qvec = embed_query(q)
    return {"q": q, "mode": mode, "items": search(mode, qvec, limit)}


@router.get("/compare")
def compare(q: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=50)) -> dict:
    """같은 질의를 두 조립안에 동시에 던진다.

    질의 임베딩은 **한 번만** 한다. 조립안이 달라도 질의 쪽 벡터는 같기 때문이고,
    비교가 조립안 차이만 보이게 하려면 그래야 한다.
    """
    qvec = embed_query(q)
    results = {}
    for mode in MODES:
        try:
            results[mode] = search(mode, qvec, limit)
        except HTTPException as exc:
            results[mode] = {"error": exc.detail}
    return {"q": q, "results": results}
