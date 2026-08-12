"""임베딩 조립안 A/B 프로브 — 30만 건에 돈과 시간을 쓰기 전에 1,000건으로 재본다.

무엇을 임베딩하느냐가 검색 품질을 정하는데, 그 답은 데이터마다 다르다.
이 데이터의 식품명은 평균 10.4자로 짧고(`소금빵`, `스파게티`), 브랜드·외국어가
섞인다. 반면 분류 체계는 결측이 0%이고 소분류만 219종이라 사실상 사람이 붙여둔
라벨이다. 그러니 "식품명만"과 "식품명+분류"가 같을 리 없다.

전량은 두 시간이 걸리지만 샘플 1,000건은 몇 분이고 몇 센트다.
**큰 데이터로 결정하지 말고 작은 데이터로 결정한다.**

비교하는 조립안 네 가지:
  A name          식품명만
  B name+cat_raw  식품명 + 분류 (원문 그대로 — '해당없음' 포함)
  C name+cat      식품명 + 분류 ('해당없음' 제거)
  D name+cat+maker  C + 제조사명

사용법:
  docker compose exec api uv run python scripts/embed_probe.py
  docker compose exec api uv run python scripts/embed_probe.py --top-k 5
"""

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

MODEL = os.environ.get("EMBEDDING_MODEL", "gemini/gemini-embedding-001")
DIM = int(os.environ.get("EMBEDDING_DIM", "768"))
BATCH = int(os.environ.get("EMBED_BATCH_SIZE", "100"))
# 무료 티어는 분당 임베딩 내용 100건. 배치 사이에 쉬어 429를 미리 피한다
PACE_SECONDS = float(os.environ.get("EMBED_PACE_SECONDS", "62"))
CACHE = Path("data/clean/.embed_probe_cache.jsonl")

# 분류가 비어 있을 때 원본이 쓰는 값. 이 문자열이 30만 건에 공통으로 들어가면
# 모든 벡터를 같은 방향으로 밀어 유사도를 희석시킨다.
EMPTY_CATEGORY = {"해당없음", "", "nan", "None"}

QUERIES = [
    "매콤한 분식 간식",
    "나트륨 낮은 튀김 간식",
    "아이 간식으로 좋은 부드러운 빵",
    "더울 때 시원하게 마실 음료",
    "밥 대신 간단히 먹는 즉석식품",
]


def cat_parts(row, drop_empty: bool) -> list[str]:
    parts = [
        str(row["식품대분류명"]),
        str(row["식품중분류명"]),
        str(row["식품소분류명"]),
    ]
    return [p for p in parts if not drop_empty or p not in EMPTY_CATEGORY]


def build_texts(df: pd.DataFrame) -> dict[str, list[str]]:
    """조립안 네 가지를 만든다. 이 함수가 이 실험의 전부다."""
    name = df["식품명"].astype(str)
    variants = {"A name": name.tolist()}

    raw, clean, with_maker = [], [], []
    for _, row in df.iterrows():
        nm = str(row["식품명"])
        raw.append(" · ".join([nm] + cat_parts(row, drop_empty=False)))
        c = " · ".join([nm] + cat_parts(row, drop_empty=True))
        clean.append(c)
        maker = str(row["제조사명"])
        with_maker.append(c + (f" · {maker}" if maker not in EMPTY_CATEGORY else ""))

    variants["B name+cat_raw"] = raw
    variants["C name+cat"] = clean
    variants["D name+cat+maker"] = with_maker
    return variants


def load_cache() -> dict:
    if not CACHE.exists():
        return {}
    cache = {}
    with CACHE.open(encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
                cache[rec["k"]] = rec["v"]
            except (json.JSONDecodeError, KeyError):
                continue
    return cache


def key_of(text: str, task: str) -> str:
    return hashlib.sha1(f"{MODEL}|{DIM}|{task}|{text}".encode()).hexdigest()


RETRY_HINT = re.compile(r"retry in ([\d.]+)s")


def embed(texts: list[str], task: str, cache: dict, stats: dict) -> np.ndarray:
    """배치 호출 + 캐시 + 페이싱. 재실행이 공짜여야 A/B를 여러 번 돌려볼 수 있다.

    무료 티어의 쿼터는 "요청 수"가 아니라 "임베딩한 내용 수"로 센다.
    100건을 한 요청에 묶어도 쿼터는 100 소모된다. 그래서 배치 크기를 키워도
    처리량이 늘지 않고, 남는 방법은 시간을 들이는 것뿐이다.
    """
    import litellm

    todo = [t for t in dict.fromkeys(texts) if key_of(t, task) not in cache]
    if todo:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        with CACHE.open("a", encoding="utf-8") as f:
            for i in range(0, len(todo), BATCH):
                chunk = todo[i : i + BATCH]
                for attempt in range(6):
                    try:
                        # dimensions= 가 맞는 이름이다. output_dimensionality= 는
                        # 조용히 무시되고 3072차원이 돌아온다 (인덱스가 4배가 된다)
                        res = litellm.embedding(
                            model=MODEL, input=chunk, dimensions=DIM, task_type=task
                        )
                        break
                    except Exception as exc:  # noqa: BLE001 — rate limit 재시도
                        if attempt == 5:
                            raise
                        # 서버가 "몇 초 뒤에 오라"고 알려주면 그 말을 듣는다.
                        # 지수 백오프보다 정확하고, 상대 서버에도 예의다.
                        hint = RETRY_HINT.search(str(exc))
                        wait = float(hint.group(1)) + 1 if hint else 2**attempt
                        stats["retries"] += 1
                        print(f"    429 — {wait:.0f}s 대기 후 재시도"
                              f" ({attempt + 1}/5)", flush=True)
                        time.sleep(wait)
                stats["calls"] += 1
                stats["tokens"] += getattr(res.usage, "prompt_tokens", 0) or 0
                for text, item in zip(chunk, res.data):
                    vec = item["embedding"]
                    cache[key_of(text, task)] = vec
                    f.write(json.dumps({"k": key_of(text, task), "v": vec}) + "\n")
                    f.flush()
                stats["new"] += len(chunk)
                print(f"    {min(i + BATCH, len(todo)):,}/{len(todo):,}", flush=True)
                if i + BATCH < len(todo) and PACE_SECONDS:
                    time.sleep(PACE_SECONDS)

    mat = np.array([cache[key_of(t, task)] for t in texts], dtype=np.float32)
    # 잘린 벡터는 L2 norm이 1이 아니다. 정규화하지 않으면 코사인이 왜곡된다
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    return mat / np.clip(norms, 1e-9, None)


def main() -> int:
    parser = argparse.ArgumentParser(description="임베딩 조립안 A/B 프로브")
    parser.add_argument("--input", default="data/sample/raw_sample.csv")
    parser.add_argument("--rows", type=int, default=0, help="앞에서 N건만 (0이면 전부)")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--report", default="reports/embed_probe.txt")
    args = parser.parse_args()

    df = pd.read_csv(args.input).fillna("")
    if args.rows:
        df = df.head(args.rows).reset_index(drop=True)
    variants = build_texts(df)
    stats = {"calls": 0, "tokens": 0, "new": 0, "retries": 0}
    cache = load_cache()

    lines = []

    def out(s=""):
        print(s, flush=True)
        lines.append(s)

    out(f"[probe] 모델 {MODEL} · {DIM}차원 · {len(df):,}건 · 조립안 {len(variants)}종")
    out()
    out("[조립안 실물] 같은 행을 네 가지로 조립하면")
    for label, texts in variants.items():
        out(f"  {label:<18} {texts[41][:74]}")
    avg = {k: sum(len(t) for t in v) / len(v) for k, v in variants.items()}
    out()
    out("[평균 길이] " + " · ".join(f"{k.split()[0]} {v:.1f}자" for k, v in avg.items()))
    out()

    doc_mats = {}
    for label, texts in variants.items():
        print(f"  임베딩: {label}")
        doc_mats[label] = embed(texts, "RETRIEVAL_DOCUMENT", cache, stats)

    print("  임베딩: 질의")
    qmat = embed(QUERIES, "RETRIEVAL_QUERY", cache, stats)

    out("=" * 78)
    for qi, q in enumerate(QUERIES):
        out(f'\n■ "{q}"')
        for label, mat in doc_mats.items():
            sims = mat @ qmat[qi]
            top = np.argsort(-sims)[: args.top_k]
            big = df.iloc[top]["식품대분류명"].tolist()
            focus = max(big.count(c) for c in set(big)) / len(big) * 100
            out(f"  {label:<18} 최고 {sims[top[0]]:.3f} · 대분류 집중도 {focus:.0f}%")
            for r in top[:3]:
                out(f"      {sims[r]:.3f}  {df.iloc[r]['식품명'][:30]:<32}"
                    f" [{df.iloc[r]['식품중분류명']}]")

    out()
    out("=" * 78)
    out(f"[cost] 호출 {stats['calls']}회 · 신규 임베딩 {stats['new']:,}건 · "
        f"입력 {stats['tokens']:,} tok · 429 재시도 {stats['retries']}회")
    out(f"       캐시 적중분은 과금되지 않습니다 (재실행은 공짜)")

    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n[done] → {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
