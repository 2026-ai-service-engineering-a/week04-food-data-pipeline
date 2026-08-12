"""규칙 파서 — 다수를 공짜로 처리하는 층.

정규식은 결정적이다. 같은 입력에 같은 출력, 무료, 즉시. LLM은 유연하지만
비결정적이고 유료다. 각자의 자리가 있고, **싼 층이 먼저**다.

층을 둘로 나눈 이유는 실측 때문이다. 전량의 고유값 34개를 보면:

  1차 `숫자+g`        16개 → 166,995행   `30g` `70g` `10g`
  2차 단위 병기        12개 →  60,292행   `200ml` `5g(ml)` `250ml(g)`
  잔여                 5개 →  19,909행   `드레싱 15g, 덮밥소스 165g`
  판단 불가            1개 →   3,138행   `1식`

2차를 만들기 전에는 잔여가 12개였다. 잔여를 **눈으로 보고** 정규식 한 줄을
더한 결과가 이 층이다. 34개는 사람이 볼 수 있는 크기이고, 보면 무엇이 필요한지
안다. 그래서 파싱 전에 세는 것이 먼저다.

## ml을 g으로 볼 것인가

`200ml`을 200g으로 적는다. 밀도 1 가정이고, 음료가 대부분이라 큰 무리는
아니지만 **가정은 가정이다.** 조용히 넘기지 않고 note에 남긴다. 나중에
"이 숫자 어디서 왔냐"는 질문에 답할 수 있어야 한다.
"""

import re

# 1차: 순수한 그램. '1회 40g' 같은 접두어까지만 허용한다
RULE_GRAM = re.compile(r"^\s*(?:1회\s*(?:제공량|섭취참고량)?\s*)?(\d+(?:[.,]\d+)?)\s*g\s*$", re.I)

# 2차: 다른 단위와 단위 병기. `200ml` `5g(ml)` `250ml(g)` `100g(ml)`
RULE_UNIT = re.compile(
    r"^\s*(?:1회\s*(?:제공량|섭취참고량)?\s*)?(\d+(?:[.,]\d+)?)\s*(g|ml)\s*"
    r"(?:\(\s*(?:g|ml)\s*\)\s*)?$",
    re.I,
)


def _to_int(num: str) -> int:
    return int(round(float(num.replace(",", "."))))


def parse_gram(text: str) -> int | None:
    """1차 규칙. 그램이 아니면 None을 돌려줄 뿐, 화내지 않는다."""
    if not isinstance(text, str):
        return None
    m = RULE_GRAM.match(text)
    return _to_int(m.group(1)) if m else None


def parse_unit(text: str) -> tuple[int, str] | None:
    """2차 규칙. (수치, 단위)를 돌려준다. ml 환산은 호출자가 결정한다."""
    if not isinstance(text, str):
        return None
    m = RULE_UNIT.match(text)
    return (_to_int(m.group(1)), m.group(2).lower()) if m else None


def parse_rule(text: str) -> tuple[int, str, str] | None:
    """두 층을 순서대로 시도한다. (그램, 층 이름, 비고) 또는 None.

    반환에 층 이름을 실어 보내는 이유: 나중에 "규칙이 푼 것"과 "LLM이 푼 것"을
    갈라서 스팟 체크할 수 있어야 한다. 검증 가능성을 데이터에 심는 것이다.
    """
    g = parse_gram(text)
    if g is not None:
        return g, "rule_g", ""

    hit = parse_unit(text)
    if hit is None:
        return None
    value, unit = hit
    if unit == "g":
        return value, "rule_unit", ""
    return value, "rule_unit", "ml을 g으로 간주(밀도 1 가정)"
