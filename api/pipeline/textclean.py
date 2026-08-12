"""문자 정리 — 정제의 최소 단위.

문자열 하나를 받아 문자열 하나를 돌려주는 순수 함수만 둔다. 파일도 DataFrame도
모르기 때문에 테스트가 쉽고, 테스트가 쉬우니 믿고 쓸 수 있다.

원본 306,307건을 전수 조사하면 오염은 54건(0.018%)뿐이다. 그런데 그 54건이
어떤 종류인지가 처방을 가른다.

  BOM(5) · 제어문자(10) · NFD(30) · 앞뒤공백(3)   고칠 수 있다 → 고쳐서 싣는다
  대체불가 문자(6) `？` `�`                   복구 불가   → 사유를 붙여 분리

`？스타곰탕`의 원래 글자가 무엇이었는지는 아무도 모른다. 추측해서 채우면
데이터가 예뻐지지만 근거 없는 값이 들어간다. **고칠 수 있으면 고치고, 못 고치면
빼놓는다.** 이 갈림이 정제 정책의 첫 결정이고, 파싱의 NULL과 답변의
"모르면 모른다"로 그대로 이어진다.
"""

import re
import unicodedata

BOM = "\ufeff"

# 되살릴 수 없는 문자. 전각 물음표는 인코딩 변환이 실패한 자리에 남는다
BROKEN = re.compile("[\ufffd\uff1f]")

# 줄바꿈·탭을 포함한 제어문자. 식품명 한가운데 개행이 든 행이 실제로 10건 있다
CONTROL = re.compile("[\u0000-\u001f\u007f]")


def strip_bom_and_controls(s: str) -> str:
    """BOM과 제어문자를 없애고 앞뒤 공백을 정리한다."""
    if not isinstance(s, str):
        return s
    s = s.replace(BOM, "")
    # 제어문자는 지우지 말고 공백으로 바꾼다. 지우면 단어가 붙어버린다
    s = CONTROL.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_nfc(s: str) -> str:
    """유니코드를 NFC로 모은다.

    NFD로 저장된 한글은 눈으로는 멀쩡한데 `==` 비교와 검색이 어긋난다.
    원본에 30건 있고, 화면에서는 절대 안 보이는 종류의 오염이다.
    """
    return unicodedata.normalize("NFC", s) if isinstance(s, str) else s


def clean_text(s: str) -> str:
    """문자 정리 전체. 순서가 있다 — 제어문자를 없앤 뒤에 정규화한다."""
    return normalize_nfc(strip_bom_and_controls(s))


def has_broken_char(s: str) -> bool:
    """되살릴 수 없는 문자가 있는가. True면 고치지 말고 분리한다."""
    return bool(BROKEN.search(s)) if isinstance(s, str) else False
