"""규칙 파서 유닛테스트.

실제 원본에 있는 34개 고유값에서 골라 썼다. 지어낸 입력으로 테스트하면
현실에 없는 형식을 지키느라 코드가 복잡해진다.

실패 케이스가 특히 중요하다. 규칙은 **못 푸는 것을 못 푼다고 말해야** 다음 층이
받는다. 억지로 숫자를 뽑으면 `1식`이 1g이 된다.
"""

import pytest

from pipeline.serving_rule import parse_gram, parse_rule, parse_unit


@pytest.mark.parametrize(
    "text,grams",
    [("30g", 30), ("70g", 70), ("210g", 210), ("4g", 4), ("1회 40g", 40), ("100 g", 100)],
)
def test_simple_gram(text, grams):
    assert parse_gram(text) == grams


@pytest.mark.parametrize("text", ["200ml", "5g(ml)", "250ml(g)", "1식", "드레싱 15g, 덮밥소스 165g"])
def test_gram_rule_declines_the_rest(text):
    """1차는 자기 것만 처리한다. 못 푸는 것에 손대지 않는다."""
    assert parse_gram(text) is None


@pytest.mark.parametrize(
    "text,expected",
    [("200ml", (200, "ml")), ("100ml", (100, "ml")), ("5g(ml)", (5, "g")),
     ("250ml(g)", (250, "ml")), ("100g(ml)", (100, "g"))],
)
def test_unit_and_paren_forms(text, expected):
    assert parse_unit(text) == expected


def test_parse_rule_reports_which_tier():
    """어느 층이 풀었는지 함께 돌려준다. 나중에 갈라서 스팟 체크하기 위해서다."""
    assert parse_rule("30g") == (30, "rule_g", "")
    grams, tier, note = parse_rule("200ml")
    assert (grams, tier) == (200, "rule_unit")
    assert "밀도" in note  # ml 환산은 가정이므로 반드시 남긴다


@pytest.mark.parametrize(
    "text",
    [
        "1식",  # 숫자가 없다
        "드레싱 15g, 덮밥소스 165g",  # 복합형
        "생·숙면 200g, 건면 100g, 당면 30g",
        "레토르트 200g 기타 25g",
        "",
        None,
    ],
)
def test_returns_none_on_failure(text):
    """실패는 None이다. 억지로 숫자를 뽑으면 '1식'이 1g이 된다."""
    assert parse_rule(text) is None


def test_decimal_and_comma():
    assert parse_gram("2.5g") == 2  # 반올림
    assert parse_gram("2,5g") == 2  # 소수점 쉼표 표기
