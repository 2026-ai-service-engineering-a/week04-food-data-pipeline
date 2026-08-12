"""스팟 체크 — 파싱 결과를 원문과 대조한다.

리포트는 "몇 %가 처리됐다"를 말하지만 "제대로 됐나"는 말하지 않는다. 커버리지
100%짜리 엉터리 파서를 만들기는 쉽다. 그래서 원문과 결과를 나란히 눈으로 본다.

`--method llm`이 이 도구의 요점이다. 1단계에서 각 행에 파싱 방법을 기록해 둔
덕에 **LLM이 만진 것만 골라볼 수 있다.** 검증 가능성을 데이터에 심어 둔 값이
여기서 돌아온다.

그리고 전량에서 llm 파싱분은 고유값 5개뿐이라 **표본 검사가 아니라 전수 검사**가
된다. 고유값으로 접었더니 검증까지 싸졌다.

사용법:
  uv run python -m pipeline.spot_check --method llm
  uv run python -m pipeline.spot_check --method rule_unit -n 5
"""

import argparse
import json
from pathlib import Path

import pandas as pd

COL = "1회 섭취참고량"


def main() -> int:
    ap = argparse.ArgumentParser(description="파싱 결과 스팟 체크")
    ap.add_argument("--input", default="data/clean/foods_parsed.parquet")
    ap.add_argument("--method", default="llm", help="rule_g · rule_unit · llm · none")
    ap.add_argument("-n", type=int, default=0, help="0이면 고유값 전부")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"입력이 없습니다: {src} — pipeline.serving을 먼저 돌리세요")
        return 1

    df = pd.read_parquet(src)
    sub = df[df["parse_method"] == args.method]
    if sub.empty:
        print(f"'{args.method}'로 파싱된 행이 없습니다")
        return 0

    # 같은 원문이 수만 행에 붙어 있다. 대조는 고유값 단위로 한다
    uniq = sub.drop_duplicates(subset=[COL])
    if args.n:
        uniq = uniq.head(args.n)

    rows = df[COL].value_counts()
    print(f"[spot ] method={args.method} · 고유값 {len(uniq)}개 / {len(sub):,}행")
    for _, r in uniq.iterrows():
        variants = json.loads(r["serving_variants"] or "[]")
        detail = f"variants={len(variants)}" if variants else ""
        note = f"  ({r['serving_note']})" if r["serving_note"] else ""
        print(f'  원문: {r[COL]!r}')
        print(f"     → serving_g={r['serving_g']}  {detail}{note}"
              f"  · {rows.get(r[COL], 0):,}행에 적용")
        for v in variants:
            print(f"       - {v['form']} {v['grams']}g")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
