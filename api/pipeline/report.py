"""리포트 — 정제는 코드가 아니라 리포트로 검증한다.

30만 줄을 사람이 셀 수는 없다. 대신 한 줄 검산을 남긴다.

    입력 = 출력 + 제외

이게 안 맞으면 어딘가에서 데이터가 새는 것이고, 맞으면 최소한 행이 증발하지는
않았다는 뜻이다. 나중에 "데이터 왜 줄었어요?"라는 질문을 받았을 때 답이 여기 있다.
"""

from pathlib import Path

import pandas as pd


def _write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8")
    print(text, end="")


def write_clean_report(path: Path, kept: pd.DataFrame, stats: dict,
                       out_path: Path, rejected_path: Path) -> None:
    n_rej = sum(stats["rejected"].values())
    checksum = stats["output_rows"] + n_rej
    rate = (kept.isna().mean() * 100).sort_values(ascending=False)
    top = [f"{c} {v:.2f}%" for c, v in rate.head(4).items() if v > 0]

    lines = [
        f"[clean] 입력: {stats['input_rows']:,}행 · {stats['input_cols']}열",
        f"[clean] 문자 정리: {stats['text_fixed']:,}행 고쳐서 실음 "
        + " · ".join(f"{c} {n:,}" for c, n in
                     sorted(stats.get("text_fixed_by_col", {}).items(), key=lambda x: -x[1])),
        f"[clean] 출력: {stats['output_rows']:,}행 · {stats['output_cols']}열 → {out_path}",
        f"[clean] 제외: {n_rej:,}행 → {rejected_path}",
    ]
    for reason, cnt in sorted(stats["rejected"].items(), key=lambda x: -x[1]):
        lines.append(f"        - {reason}: {cnt:,}")
    lines += [
        f"[clean] 열별 결측률(출력 기준 상위): {' · '.join(top) if top else '없음'}",
        f"[check] {stats['input_rows']:,} = {stats['output_rows']:,} + {n_rej:,}"
        f"  → {'OK' if checksum == stats['input_rows'] else '불일치! 데이터가 샜다'}",
        f"[time ] {stats['elapsed_sec'] / 60:.1f}분",
    ]
    _write(path, lines)


def write_parse_report(path: Path, stats: dict) -> None:
    """파싱 리포트 — 커버리지를 고유값과 행 양쪽으로 낸다.

    행 기준만 보면 "몇 %를 처리했다"는 알지만 **얼마를 지불했는지**는 모른다.
    고유값 기준이 곧 호출 수이고, 호출 수가 곧 비용이다.
    """
    u, r = stats["uniq"], stats["rows"]
    lines = [
        f"[count] 1회 섭취참고량 고유값: {stats['n_uniq']:,}개 ({stats['n_rows']:,}행 중)",
        f"        └ 30만 건이 {stats['n_uniq']}개 문자열을 나눠 씁니다."
        " 규정 표준값이라 사실상 통제 어휘입니다.",
        f"[rule ] 1차(숫자+g)      {u['rule_g']:>3}개 고유값 → {r['rule_g']:>7,}행",
        f"[rule ] 2차(단위 병기)    {u['rule_unit']:>3}개 고유값 → {r['rule_unit']:>7,}행",
        f"[llm  ] {u['llm']:>3}개 고유값 호출 → {r['llm']:>7,}행",
        f"        입력 {stats['tokens_in']:,} tok · 출력 {stats['tokens_out']:,} tok"
        f" · ${stats['cost_usd']:.4f}",
        f"[none ] {u['none']:>3}개 고유값 + 빈 값 → serving_g = NULL"
        f" ({r['none']:,}행)",
        f"[done ] rule {r['rule_g'] + r['rule_unit']:,} · llm {r['llm']:,}"
        f" · none {r['none']:,} → {stats['output']}",
        "",
        f"[cost ] 실제 지출          ${stats['cost_usd']:.4f}"
        f"  (고유값 {u['llm']}건 호출)",
        f"[cost ] 행 단위였다면      ${stats['naive_cost_usd']:.2f}"
        f"   ({stats['naive_calls']:,}건 호출 추정)",
        f"        └ {stats['saving_ratio']:,.0f}배. nunique() 한 줄의 값입니다.",
    ]
    _write(path, lines)
