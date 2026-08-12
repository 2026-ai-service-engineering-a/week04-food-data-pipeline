"""2단계 — 1회 섭취참고량 파싱. **먼저 세고, 규칙으로 접고, 남은 것만 LLM.**

이 파일의 첫 세 줄이 이번 주에서 가장 값싼 코드다.

    uniq = df[COL].dropna().unique()

30만 건이 실은 34개 문자열이었다. 규정 표준값이라 자유 텍스트처럼 보였을 뿐
사실상 통제 어휘다. 행 단위로 돌리면 LLM을 42,378번 부르고 30달러가 나가는데,
고유값으로 접으면 5번에 1센트도 안 든다.

**데이터를 안 보고 견적을 내면 3만 배 틀린다.** "31만 건 LLM 파싱은 얼마죠?"
라는 질문 자체가 함정이고, nunique() 한 줄이 그 질문을 무의미하게 만든다.

비용 사다리가 여기서 처음 실전이 된다.
  세기(공짜) → 규칙(공짜) → LLM(비싸다)

사용법:
  uv run python -m pipeline.serving --input data/clean/foods_clean.parquet
  uv run python -m pipeline.serving --show-residual      # 잔여를 눈으로 본다
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

from pipeline.report import write_parse_report
from pipeline.serving_rule import parse_rule

COL = "1회 섭취참고량"
CACHE = Path("data/clean/.serving_cache.json")

# 건당 비용 추정치. 행 단위로 돌렸다면 얼마였을지를 리포트에 적기 위한 것이고,
# 정확한 값은 각자의 요금표에서 확인한다
COST_PER_CALL_USD = 0.0007


def load_cache() -> dict:
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def classify(uniq: list[str], cache: dict, llm_limit: int, debug: bool) -> tuple[dict, dict]:
    """고유값 하나당 한 번만 판정한다. (판정 결과, 사용량 집계)."""
    result, usage = {}, {"in": 0, "out": 0, "calls": 0}
    residual = []

    for text in uniq:
        hit = parse_rule(text)
        if hit:
            grams, tier, note = hit
            result[text] = {"serving_g": grams, "method": tier, "variants": [], "note": note}
        else:
            residual.append(text)

    for text in residual:
        if text in cache:
            result[text] = cache[text]
            continue
        if usage["calls"] >= llm_limit:
            result[text] = {"serving_g": None, "method": "none",
                            "variants": [], "note": "LLM 상한 초과 — 미처리"}
            continue
        from pipeline.serving_llm import parse_with_llm

        info, stats = parse_with_llm(text, debug=debug)
        variants = [v.model_dump() for v in info.variants]

        # 대표값은 코드가 정한다. LLM에게는 형태를 갈라내는 일만 맡긴다.
        #   `액상 150ml, 호상 100ml(g)`에서 모델이 대표를 못 고르고 null을 냈다.
        #   형태가 갈라져 있는데 대표가 없다고 "모름"으로 두면 정보를 버리는 것이고,
        #   무엇을 대표로 삼을지는 규칙으로 정할 수 있는 문제다 — 첫 형태를 쓴다.
        #   3주차의 "믿되, 재계산하라"와 같은 자리다.
        serving_g = info.serving_g
        if serving_g is None and variants:
            serving_g = variants[0]["grams"]
            info.note = (info.note + " · " if info.note else "") + "대표값은 첫 형태(코드 판정)"

        rec = {
            "serving_g": serving_g,
            "method": "llm" if serving_g is not None else "none",
            "variants": variants,
            "note": info.note,
        }
        result[text] = cache[text] = rec
        usage["in"] += stats["in"]
        usage["out"] += stats["out"]
        usage["calls"] += 1
        print(f"  [llm ] {text[:44]!r} → serving_g={rec['serving_g']}"
              f" variants={len(rec['variants'])}", flush=True)

    return result, usage


def main() -> int:
    ap = argparse.ArgumentParser(description="1회 섭취참고량 파싱 (고유값 단위)")
    ap.add_argument("--input", default="data/clean/foods_clean.parquet")
    ap.add_argument("--output", default="data/clean/foods_parsed.parquet")
    ap.add_argument("--report", default="reports/parse_report.txt")
    ap.add_argument("--llm-limit", type=int, default=int(os.environ.get("LLM_LIMIT", "100")))
    ap.add_argument("--show-residual", action="store_true", help="규칙이 못 푼 고유값을 전부 출력")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"입력이 없습니다: {src} — pipeline.clean을 먼저 돌리세요", file=sys.stderr)
        return 1

    t0 = time.time()
    df = pd.read_parquet(src)
    series = df[COL]
    uniq = sorted(x for x in series.dropna().unique())
    n_uniq, n_rows = len(uniq), len(df)

    print(f"[count] {COL} 고유값: {n_uniq:,}개 ({n_rows:,}행 중)", flush=True)

    if args.show_residual:
        rows = series.value_counts()
        residual = [t for t in uniq if parse_rule(t) is None]
        print(f"[residual] 규칙이 못 푼 고유값 {len(residual)}개 — 전부 출력합니다")
        for t in sorted(residual, key=lambda x: -rows.get(x, 0)):
            print(f"  {rows.get(t, 0):>7,}  {t}")
        return 0

    cache = {} if args.no_cache else load_cache()
    cached_before = len(cache)
    decisions, usage = classify(uniq, cache, args.llm_limit, args.debug)
    if not args.no_cache:
        save_cache(cache)
    if cached_before and usage["calls"] == 0:
        print(f"[skip ] 캐시에서 {cached_before}개 고유값 건너뜀 ({CACHE})")

    # 고유값 판정을 행에 되붙인다. 여기가 접었던 것을 펴는 자리다
    df["serving_g"] = series.map(lambda t: decisions.get(t, {}).get("serving_g")
                                 if pd.notna(t) else None).astype("Int64")
    df["parse_method"] = series.map(lambda t: decisions.get(t, {}).get("method", "none")
                                    if pd.notna(t) else "none")
    df["serving_note"] = series.map(lambda t: decisions.get(t, {}).get("note", "")
                                    if pd.notna(t) else "1회 제공량 정보 없음 (원문: '')")
    df["serving_variants"] = series.map(
        lambda t: json.dumps(decisions.get(t, {}).get("variants", []), ensure_ascii=False)
        if pd.notna(t) else "[]")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)

    by_method = df["parse_method"].value_counts().to_dict()
    uniq_by = {}
    for text, rec in decisions.items():
        uniq_by[rec["method"]] = uniq_by.get(rec["method"], 0) + 1
    naive_calls = int(sum(v for k, v in by_method.items() if k in ("llm", "none"))
                      - int(series.isna().sum()))
    cost = (usage["in"] * 0.15 + usage["out"] * 0.60) / 1_000_000

    write_parse_report(Path(args.report), {
        "n_uniq": n_uniq, "n_rows": n_rows,
        "uniq": {"rule_g": uniq_by.get("rule_g", 0), "rule_unit": uniq_by.get("rule_unit", 0),
                 "llm": uniq_by.get("llm", 0), "none": uniq_by.get("none", 0)},
        "rows": {"rule_g": by_method.get("rule_g", 0), "rule_unit": by_method.get("rule_unit", 0),
                 "llm": by_method.get("llm", 0), "none": by_method.get("none", 0)},
        "tokens_in": usage["in"], "tokens_out": usage["out"], "cost_usd": cost,
        "naive_calls": max(naive_calls, 0),
        "naive_cost_usd": max(naive_calls, 0) * COST_PER_CALL_USD,
        "saving_ratio": (max(naive_calls, 0) * COST_PER_CALL_USD / cost) if cost else 0,
        "output": out, "elapsed_sec": time.time() - t0,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
