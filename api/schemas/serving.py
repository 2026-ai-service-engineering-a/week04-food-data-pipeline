"""1회 섭취참고량 파싱의 출력 스키마.

`serving_g: int | None`이 이 파일의 요점이다. **"모름"이 일급 시민**이고,
스키마가 그것을 허용하지 않으면 LLM은 빈칸을 채우고 싶어 한다. `1식`처럼
숫자가 없는 원문에 그럴듯한 수를 지어내는 것을 막는 것은 프롬프트의 당부가
아니라 타입이다.

variants는 복합형을 위해 있다. `드레싱 15g, 덮밥소스 165g`은 대표값 하나로
줄일 수 없고, 줄이면 화면에서 "덮밥으로 먹으면 얼마인가"에 답할 수 없다.
"""

from pydantic import BaseModel, Field


class ServingVariant(BaseModel):
    """형태별 제공량. `건면 100g`처럼 한 제품이 여러 형태로 팔릴 때 쓴다."""

    form: str = Field(description="형태 이름. 예: 생·숙면, 건면, 드레싱")
    grams: int = Field(description="그 형태의 1회 제공량(g)")


class ServingInfo(BaseModel):
    """원문 하나를 구조화한 결과.

    LLM에게 이 스키마를 강제하면 "약 200g 정도" 같은 문장이 못 나온다.
    3주차 instructor가 파이프라인 안으로 이사 온 자리다.
    """

    serving_g: int | None = Field(
        default=None,
        description="대표 1회 제공량(g). 숫자로 환산할 수 없으면 반드시 null. 지어내지 마라",
    )
    variants: list[ServingVariant] = Field(
        default_factory=list, description="형태가 여럿이면 전부. 하나뿐이면 빈 목록"
    )
    confidence: str = Field(default="low", description="high 또는 low")
    note: str = Field(default="", description="판단 근거나 가정. 없으면 빈 문자열")
