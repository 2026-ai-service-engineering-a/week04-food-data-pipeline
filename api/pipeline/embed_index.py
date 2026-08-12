"""4단계 색인 — foods 테이블을 읽어 벡터로 만들고 Chroma에 넣는다.

1회전과 대비되는 지점이 여기다. 섭취참고량은 고유값이 34개라 **접을 수 있었고**,
그래서 LLM 호출이 6건으로 끝났다. 식품명은 26만 개가 전부 다르다. 접을 수 없다.
접을 수 없는 배치에는 접는 대신 **안전장치**를 단다.

  중간 저장    이미 넣은 식품코드는 다시 임베딩하지 않는다
  재개         끊긴 자리에서 이어 간다 (세 시간짜리 작업이다)
  진행 로그    건수·경과·예상 잔여를 찍는다. 안 찍으면 멈춘 건지 도는 건지 모른다
  429 대기     응답의 retryDelay를 읽어 그만큼 기다린다. 지수 백오프로 찍지 않는다
  --limit      전량 전에 작게 재본다

무엇을 임베딩할지는 6-1절의 A/B 실험이 정했다. **식품명 + 대/중/소분류**다.
식품명만으로는 평균 10.4자라 의미 신호가 얕고, 제조사명은 벡터에 넣지 않는다 —
제조사로 찾는 것은 SQL의 일이다.

사용법:
  docker compose run --rm index-load
  docker compose run --rm index-load --limit 1000
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@db:5432/food")
CHROMA_HOST = os.environ.get("CHROMA_HOST", "chroma")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8000"))
MODEL = os.environ.get("EMBEDDING_MODEL", "gemini/gemini-embedding-001")
DIM = int(os.environ.get("EMBEDDING_DIM", "768"))
BATCH = int(os.environ.get("EMBED_BATCH_SIZE", "100"))
COLLECTION = "foods_name_cat"

# 100만 토큰당 단가. 정확한 값은 요금표에서 확인한다 — 여기 값은 리포트용 추정이다
PRICE_PER_MTOK = float(os.environ.get("EMBEDDING_PRICE_PER_MTOK", "0.15"))

# 모든 문서에 공통으로 들어가는 문자열은 벡터를 같은 방향으로 밀어 유사도를
# 희석시킨다. '해당없음'이 26만 건에 들어 있으면 그건 신호가 아니라 배경이다
EMPTY_CATEGORY = {"해당없음", "", "nan", "None", None}

# HNSW 색인 파라미터. 기본값(max_neighbors=16, ef_construction=100)으로 26만
# 벡터를 넣으면 recall@10이 68%까지 떨어진다. 열 건 중 셋을 놓친다는 뜻이다.
#   max_neighbors   그래프의 이웃 수. 크면 recall이 오르고 색인이 커진다
#   ef_construction 색인을 만들 때 살펴보는 후보 수. 크면 품질이 오르고 적재가 느려진다
#   ef_search       질의할 때 살펴보는 후보 수. 크면 recall이 오르고 질의가 느려진다
# 셋 다 "정확도를 시간·용량으로 사는" 손잡이다. 벡터 DB는 근사이고,
# 근사의 품질은 기본값이 아니라 이 숫자들이 정한다.
HNSW = {
    "space": "cosine",
    "max_neighbors": int(os.environ.get("HNSW_M", "32")),
    "ef_construction": int(os.environ.get("HNSW_EF_CONSTRUCTION", "200")),
    "ef_search": int(os.environ.get("HNSW_EF_SEARCH", "200")),
}

RETRY_DELAY = re.compile(r"retryDelay['\"]?[:\s]+['\"]?(\d+(?:\.\d+)?)")


def assemble(row: dict) -> str:
    """무엇을 임베딩할 것인가 — 6-1절 실험의 결론이 이 함수다.

    식품명 · 대분류 · 중분류 · 소분류. 비어 있는 조각은 넣지 않는다.
    """
    parts = [row["name"]]
    for key in ("category_big", "category_mid", "category_small"):
        value = (row.get(key) or "").strip()
        if value not in EMPTY_CATEGORY:
            parts.append(value)
    return " · ".join(parts)


def embed(texts: list[str], task_type: str) -> tuple[list[list[float]], int]:
    """LiteLLM 경유 임베딩. 파라미터 세 개가 전부 함정이다.

    ① 차원 축소는 `dimensions=`다. `output_dimensionality=`는 예외도 경고도
       없이 무시되고 3072차원이 돌아온다. 인덱스가 4배가 된다
    ② 색인용과 질의용 임베딩이 다르다. task_type을 나눠야 한다
    ③ 축소된 벡터는 L2 norm이 1이 아니다 (768로 자르면 0.59). 정규화한다
    """
    import litellm

    res = litellm.embedding(
        model=MODEL,
        input=texts,
        dimensions=DIM,  # output_dimensionality가 아니다
        task_type=task_type,
    )
    vectors = [normalize(d["embedding"]) for d in res.data]
    tokens = getattr(res, "usage", None)
    return vectors, int(getattr(tokens, "total_tokens", 0) or 0)


def normalize(vec: list[float]) -> list[float]:
    """자른 벡터는 길이가 1이 아니다. 정규화 없이 코사인을 재면
    길이가 유사도로 새어 들어온다."""
    norm = sum(x * x for x in vec) ** 0.5
    return [x / norm for x in vec] if norm else vec


def sleep_for_retry(exc: Exception) -> float:
    """429는 서버가 '언제 오라'고 알려 주는 응답이다. 그 값을 읽는다.

    지수 백오프로 찍으면 서버가 5초를 말했는데 60초를 기다리거나, 60초를
    말했는데 2초 만에 다시 두드린다. 둘 다 손해다.
    """
    match = RETRY_DELAY.search(str(exc))
    return float(match.group(1)) if match else 10.0


def fetch_rows(limit: int | None) -> list[dict]:
    import psycopg
    from psycopg.rows import dict_row

    sql = ("select code, name, category_big, category_mid, category_small,"
           " maker, sodium_mg from foods order by code")
    if limit:
        sql += f" limit {int(limit)}"
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return cur.fetchall()


def get_collection():
    import chromadb

    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    return client.get_or_create_collection(
        COLLECTION,
        metadata={f"hnsw:{k}": v for k, v in HNSW.items()},
    )


def already_indexed(collection, codes: list[str]) -> set[str]:
    """이미 넣은 것은 다시 임베딩하지 않는다. 재개의 근거가 이 한 함수다."""
    done: set[str] = set()
    for i in range(0, len(codes), 5000):
        got = collection.get(ids=codes[i:i + 5000], include=[])
        done.update(got["ids"])
    return done


def main() -> int:
    ap = argparse.ArgumentParser(description="foods 테이블 → Chroma 벡터 인덱스")
    ap.add_argument("--limit", type=int, default=None, help="앞의 N행만 (맛보기)")
    ap.add_argument("--batch", type=int, default=BATCH)
    ap.add_argument("--report", default="reports/embed_report.txt")
    args = ap.parse_args()

    t0 = time.time()
    rows = fetch_rows(args.limit)
    if not rows:
        print("foods 테이블이 비어 있습니다 — pipeline.load_pg를 먼저 돌리세요",
              file=sys.stderr)
        return 1

    collection = get_collection()
    done = already_indexed(collection, [r["code"] for r in rows])
    todo = [r for r in rows if r["code"] not in done]

    print(f"[index] {COLLECTION} · {MODEL} · {DIM}차원 · 배치 {args.batch}")
    print(f"[index] 대상 {len(rows):,}행 · 이미 있음 {len(done):,} · 넣을 것 {len(todo):,}")
    if not todo:
        # "할 일이 없음"은 실패가 아니다. compose가 이 종료 코드를 본다
        print("[done ] 이미 다 들어 있습니다")
        return 0

    tokens = retries = 0
    for i in range(0, len(todo), args.batch):
        chunk = todo[i:i + args.batch]
        texts = [assemble(r) for r in chunk]
        while True:
            try:
                vectors, used = embed(texts, "RETRIEVAL_DOCUMENT")
                tokens += used
                break
            except Exception as exc:  # noqa: BLE001 — 429든 일시 장애든 대응은 같다
                wait = sleep_for_retry(exc)
                retries += 1
                print(f"[retry] {type(exc).__name__} — {wait:.0f}초 대기 "
                      f"(누적 {retries}회)", file=sys.stderr)
                time.sleep(wait)

        collection.add(
            ids=[r["code"] for r in chunk],
            embeddings=vectors,
            documents=texts,
            # 메타데이터는 **where 필터용만**이다. 답에 쓸 내용은 식품코드로
            # PostgreSQL 원본에서 꺼낸다. 벡터 DB는 색인이지 원본이 아니다
            metadatas=[{"category_big": r["category_big"] or "",
                        "maker": r["maker"] or "",
                        "sodium_mg": float(r["sodium_mg"] or -1)} for r in chunk],
        )

        seen = i + len(chunk)
        elapsed = time.time() - t0
        rate = seen / elapsed
        left = (len(todo) - seen) / rate if rate else 0
        print(f"[embed] {seen:,}/{len(todo):,} · {rate:.0f}건/초 · "
              f"경과 {elapsed / 60:.1f}분 · 남음 {left / 60:.1f}분", flush=True)

    elapsed = time.time() - t0
    cost = tokens / 1_000_000 * PRICE_PER_MTOK
    total = collection.count()
    lines = [
        f"[index] {COLLECTION} · {MODEL} · {DIM}차원",
        f"[index] HNSW {HNSW}",
        f"[embed] {len(todo):,}건 · 입력 {tokens:,} tok · ${cost:.2f} · 429 재시도 {retries}회",
        f"[done ] 컬렉션 {total:,}건 · 소요 {elapsed / 60:.0f}분",
    ]
    print("\n".join(lines))
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[done ] 리포트 → {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
