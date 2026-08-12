"""문자 정리 유닛테스트 — 정상 케이스와 오염 케이스를 함께 둔다.

"오염을 잡는다"만 검사하면 멀쩡한 문자열을 망가뜨려도 통과한다.
잡는 것과 **건드리지 않는 것**을 같이 봐야 한다.
"""

import unicodedata

import pytest

from pipeline.textclean import clean_text, has_broken_char, normalize_nfc, strip_bom_and_controls


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("\ufeff우리밀 한입 스콘 초코칩", "우리밀 한입 스콘 초코칩"),  # BOM
        ("퓔렌 프로틴 츄 망고향\n(퓔렌 프로틴 츄)", "퓔렌 프로틴 츄 망고향 (퓔렌 프로틴 츄)"),
        ("  앞뒤 공백  ", "앞뒤 공백"),
        ("탭\t사이", "탭 사이"),
        ("정상 식품명", "정상 식품명"),  # 멀쩡한 것은 그대로
    ],
)
def test_strip_bom(raw, expected):
    assert strip_bom_and_controls(raw) == expected


def test_control_char_becomes_space_not_removed():
    """제어문자를 지우면 단어가 붙는다. 공백으로 바꿔야 한다."""
    assert strip_bom_and_controls("찹쌀유과\n(찹쌀연사유과)") == "찹쌀유과 (찹쌀연사유과)"


def test_nfc_normalize():
    """NFD로 분해된 한글은 눈으로 같아 보여도 다른 문자열이다."""
    nfd = "한"  # 자모로 분해된 '한'
    assert nfd != "한"
    assert normalize_nfc(nfd) == "한"


def test_detect_broken_char():
    assert has_broken_char("\uff1f스타곰탕 냉면 무김치")
    assert has_broken_char("햇반컵반 스팸\uff1f마요덮밥")
    assert has_broken_char("\ufffd깨진 문자")
    assert not has_broken_char("정상 식품명")
    assert not has_broken_char("반각 물음표는 정상 문자다?")


def test_clean_text_is_idempotent():
    """두 번 정리해도 같아야 한다. 파이프라인은 몇 번이고 다시 돌린다."""
    once = clean_text("\ufeff퓔렌\n프로틴  츄 ")
    assert clean_text(once) == once


def test_non_string_passes_through():
    """NaN·숫자가 섞여 들어와도 죽지 않는다."""
    assert strip_bom_and_controls(None) is None
    assert clean_text(3.14) == 3.14
