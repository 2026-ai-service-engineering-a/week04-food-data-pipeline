"""LLM 잔여 파서 — 규칙이 손든 것만 받는다.

3주차의 instructor가 파이프라인 안으로 이사 왔다. 런타임 서비스가 아니라
**배치 데이터 처리 도구**로서의 LLM이고, 자리가 마지막인 것이 핵심이다.

전량에서 여기로 오는 것은 고유값 **5개**다. 행으로는 19,909행이지만 호출은
5번이다. 같은 문자열을 4만 번 다시 물을 이유가 없다.

프롬프트가 짧은 이유: 스키마가 대부분의 일을 한다. `serving_g: int | None`이
이미 "모르면 null"을 강제하므로, 문장으로 당부할 것은 판단 기준뿐이다.
"""

import json
import os

from schemas.serving import ServingInfo

MODEL = os.environ.get("PARSER_MODEL", "openai/gpt-5-mini")

SYSTEM = (
    "너는 식품 표시사항의 '1회 섭취참고량' 원문을 구조화하는 파서다. "
    "원문에 있는 것만 옮겨라. 지어내지 마라. "
    "숫자로 환산할 수 없으면 serving_g를 null로 두고 note에 이유를 적어라. "
    "형태가 여럿이면 variants에 전부 담고, serving_g에는 대표(첫) 형태를 넣어라."
)


def parse_with_llm(text: str, debug: bool = False) -> tuple[ServingInfo, dict]:
    """원문 하나를 ServingInfo로. (결과, 사용량)을 돌려준다."""
    import instructor
    import litellm

    client = instructor.from_litellm(litellm.completion)
    user = f"다음 '1회 섭취참고량' 원문을 구조화해라.\n원문: {text!r}"

    if debug:
        print(f"[debug] PARSER PROMPT ─ system: {SYSTEM}")
        print(f"[debug] PARSER PROMPT ─ user: {user}")

    info, completion = client.chat.completions.create_with_completion(
        model=MODEL,
        response_model=ServingInfo,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        max_retries=2,
    )
    usage = getattr(completion, "usage", None)
    stats = {
        "in": getattr(usage, "prompt_tokens", 0) or 0,
        "out": getattr(usage, "completion_tokens", 0) or 0,
    }
    if debug:
        print(f"[debug] PARSER RAW OUTPUT: {json.dumps(info.model_dump(), ensure_ascii=False)}")
        print(f"[debug] tokens in {stats['in']} · out {stats['out']}")
    return info, stats
