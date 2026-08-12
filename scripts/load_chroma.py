"""이미 뽑아둔 벡터를 Chroma에 적재한다. **재임베딩하지 않는다.**

`scripts/embed_probe.py`가 남긴 `data/clean/.probe_*.f32`를 읽어 chroma 서비스의
컬렉션으로 옮깁니다. API 호출이 0건이라 돈이 들지 않고, 끊겨도 이어 받습니다.

임베딩과 적재를 나눈 이유가 있습니다. 비싼 것은 임베딩이고 적재는 공짜인데,
둘을 한 스크립트에 묶으면 적재가 실패할 때마다 임베딩을 다시 하게 됩니다.
**비싼 단계의 산출물은 파일로 떨어뜨려 두고, 싼 단계는 언제든 다시 돌린다.**

컬렉션 두 개를 만듭니다:
  foods_name      A 조립안 (식품명만)          — 비교용
  foods_name_cat  C 조립안 (식품명 + 분류)     — 서비스가 쓰는 것

사용법:
  docker compose run --rm index-load
  docker compose run --rm index-load --only C --batch 2000
"""

import argparse
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(os.environ.get("DATA_DIR", "data")) / "clean"
SOURCE = DATA / ".probe_source.parquet"
DIM = int(os.environ.get("EMBEDDING_DIM", "768"))
HOST = os.environ.get("CHROMA_HOST", "chroma")
PORT = int(os.environ.get("CHROMA_PORT", "8000"))

EMPTY_CATEGORY = {"해당없음", "", "nan", "None"}

# HNSW 색인 파라미터. 기본값(max_neighbors=16, ef_construction=100)으로 26만 벡터를
# 넣으면 recall@10이 68%까지 떨어진다. 열 건 중 셋을 놓친다는 뜻이다.
#   max_neighbors  그래프의 이웃 수. 크면 recall이 오르고 색인이 커진다
#   ef_construction 색인을 만들 때 살펴보는 후보 수. 크면 품질이 오르고 적재가 느려진다
#   ef_search      질의할 때 살펴보는 후보 수. 크면 recall이 오르고 질의가 느려진다
# 셋 다 "정확도를 시간·용량으로 사는" 손잡이다. 벡터 DB는 근사이고,
# 근사의 품질은 기본값이 아니라 이 숫자들이 정한다.
HNSW = {
    "space": "cosine",
    "max_neighbors": int(os.environ.get("HNSW_M", "32")),
    "ef_construction": int(os.environ.get("HNSW_EF_CONSTRUCTION", "200")),
    "ef_search": int(os.environ.get("HNSW_EF_SEARCH", "200")),
}

VARIANTS = {
    "A": {"collection": "foods_name", "label": "식품명만"},
    "C": {"collection": "foods_name_cat", "label": "식품명 + 대/중/소분류"},
}


def build_text(row, tag: str) -> str:
    if tag == "A":
        return str(row["식품명"])
    cats = [str(row[c]) for c in ("식품대분류명", "식품중분류명", "식품소분류명")]
    return " · ".join([str(row["식품명"])] + [c for c in cats if c not in EMPTY_CATEGORY])


def wait_for_chroma(client, timeout: int = 120):
    """chroma 서비스가 뜰 때까지 기다린다. depends_on은 기동 순서만 보장한다."""
    deadline = time.time() + timeout
    while True:
        try:
            client.heartbeat()
            return
        except Exception as exc:  # noqa: BLE001
            if time.time() > deadline:
                raise SystemExit(f"chroma에 연결하지 못했습니다 ({HOST}:{PORT}): {exc}")
            time.sleep(2)


def load_variant(client, df: pd.DataFrame, tag: str, batch: int) -> None:
    vec_path = DATA / f".probe_{tag}.f32"
    if not vec_path.exists():
        print(f"[{tag}] {vec_path} 없음 — 건너뜁니다")
        return

    meta = VARIANTS[tag]
    texts = np.array([build_text(r, tag) for _, r in df.iterrows()], dtype=object)
    uniq, inverse = np.unique(texts, return_inverse=True)
    n = len(uniq)
    mat = np.memmap(vec_path, dtype=np.float32, mode="r", shape=(n, DIM))

    # 고유값 하나당 대표 행 하나. 같은 문장을 쓰는 행이 여럿이면 첫 행을 싣는다
    first_row = np.full(n, -1, dtype=np.int64)
    for row_i, u_i in enumerate(inverse):
        if first_row[u_i] < 0:
            first_row[u_i] = row_i

    col = client.get_or_create_collection(
        name=meta["collection"],
        # 임베딩은 우리가 직접 넣는다. chroma가 다시 계산하게 두면 안 된다
        embedding_function=None,
        metadata={"recipe": tag, "dim": DIM},
        configuration={"hnsw": HNSW},
    )
    done = col.count()
    if done >= n:
        print(f"[{tag}] {meta['collection']} 이미 {done:,}건 — 건너뜁니다")
        return
    if done:
        print(f"[{tag}] 재개: {done:,}/{n:,}")

    t0 = time.time()
    for s in range(done, n, batch):
        e = min(s + batch, n)
        rows = df.iloc[first_row[s:e]]
        block = np.array(mat[s:e], dtype=np.float32)
        # 잘린 벡터는 norm이 1이 아니다. 코사인 공간에 넣기 전에 정규화한다
        block /= np.clip(np.linalg.norm(block, axis=1, keepdims=True), 1e-9, None)
        col.upsert(
            ids=[f"{tag}:{i}" for i in range(s, e)],
            embeddings=block.tolist(),
            documents=uniq[s:e].tolist(),
            metadatas=[
                {
                    "code": str(r["식품코드"]),
                    "name": str(r["식품명"]),
                    "category_big": str(r["식품대분류명"]),
                    "category_mid": str(r["식품중분류명"]),
                    "category_small": str(r["식품소분류명"]),
                    "maker": str(r["제조사명"]),
                }
                for _, r in rows.iterrows()
            ],
        )
        el = time.time() - t0
        rate = (e - done) / max(el, 1e-9)
        print(f"  [{tag}] {e:,}/{n:,} · {rate:.0f}건/초 · 잔여 {(n - e) / max(rate, 1e-9) / 60:.0f}분",
              flush=True)

    print(f"[{tag}] {meta['collection']} {col.count():,}건 ({meta['label']})")


def main() -> int:
    ap = argparse.ArgumentParser(description="프로브 벡터를 chroma에 적재 (재임베딩 없음)")
    ap.add_argument("--only", default="", help="A 또는 C만 (비우면 있는 것 전부)")
    ap.add_argument("--batch", type=int, default=2000)
    args = ap.parse_args()

    import chromadb

    client = chromadb.HttpClient(host=HOST, port=PORT)
    wait_for_chroma(client)
    print(f"[chroma] {HOST}:{PORT} 연결")

    # 적재할 것이 없는 것은 실패가 아니다.
    #   chroma 인덱스를 통째로 받은 학생에게는 벡터 파일이 없고, 그게 정상이다.
    #   여기서 1을 돌려주면 api가 depends_on에 걸려 아예 뜨지 않는다.
    #   "할 일이 없음"과 "실패"를 구분하지 않으면 정상 경로가 막힌다.
    if not SOURCE.exists():
        filled = [c for c in client.list_collections()
                  if client.get_collection(c if isinstance(c, str) else c.name).count() > 0]
        if filled:
            print(f"[skip] 벡터 파일이 없지만 컬렉션이 이미 차 있습니다 ({len(filled)}개)")
        else:
            print("[skip] 적재할 벡터도 컬렉션도 없습니다. 의미 검색 없이 뜹니다.")
            print("       받아서 쓰기: chroma_foods.tar.gz 또는 probe_vectors.tar.gz 를 data/dist/ 에")
        return 0

    df = pd.read_parquet(SOURCE).fillna("")
    print(f"[source] {len(df):,}행")

    tags = [args.only.upper()] if args.only else list(VARIANTS)
    for tag in tags:
        if tag not in VARIANTS:
            print(f"알 수 없는 조립안: {tag}", file=sys.stderr)
            return 1
        load_variant(client, df, tag, args.batch)

    print("\n[done] 컬렉션 목록:")
    for c in client.list_collections():
        name = c if isinstance(c, str) else c.name
        print(f"  {name}: {client.get_collection(name).count():,}건")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
