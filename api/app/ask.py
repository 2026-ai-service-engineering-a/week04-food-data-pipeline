"""RAG 질의응답 — 30만 건이 아니라 5건을 준다.

RAG의 본체가 이 한 줄이다. 전부 주는 것이 아니라 **찾아서 준다.** 30만 건을
컨텍스트에 넣을 수는 없고, 넣을 수 있어도 넣으면 안 된다. 컨텍스트가 곧 비용이다.

LLM이 이번 주에 런타임으로 등장하는 유일한 자리이기도 하다. 정제도 파싱도
검색도 LLM 없이 했다. 여기서 부르는 이유는 **문장으로 답해야 하기 때문**이지
찾기 위해서가 아니다. 찾는 일은 앞의 임베딩이 이미 끝냈다.

그리고 1회전의 정직한 NULL이 여기서 문장이 된다. 근거에 없으면 없다고 답한다.
166열 중 17열만 실었으니 없는 정보가 많고, **없는 것을 없다고 말하는 것이
이 시스템의 일**이다.
"""

import logging
import os

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.semantic import search

router = APIRouter(tags=["ask"])

MODEL = os.environ.get("PARSER_MODEL", "openai/gpt-5-mini")
TOP_K = int(os.environ.get("ASK_TOP_K", "5"))

# LOG_LEVEL=debug면 LLM이 실제로 받은 것을 전부 찍는다. RAG에서 가장 자주
# 나오는 질문이 "왜 이렇게 답했지"이고, 답은 늘 컨텍스트에 있다.
# 컨텍스트를 볼 수 없는 RAG는 고칠 수도 없다
log = logging.getLogger("ask")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "info").upper())

SYSTEM = """당신은 가공식품 영양 정보를 안내합니다.

아래 '근거'에 있는 식품만 가지고 답하세요. 규칙:
- 근거에 없는 제품·수치는 절대 지어내지 마세요.
- 값이 null이면 "정보 없음"이라고 쓰세요. 0으로 바꾸지 마세요.
- 나트륨은 100g 기준값입니다. 1회 제공량(serving_g)이 있으면 환산값도 언급하세요.
- 근거로 답할 수 없으면 "제공된 자료로는 답할 수 없습니다"라고 답하세요.
- 한국어로, 3문장 이내로 답하세요."""


class AskRequest(BaseModel):
    q: str = Field(..., description="자연어 질문")
    limit: int = Field(TOP_K, ge=1, le=20, description="컨텍스트에 넣을 근거 수")
    sodium_max: float | None = Field(None, description="나트륨 상한")


def build_context(items: list[dict]) -> str:
    """검색 결과를 LLM이 읽을 문장으로. **여기 없는 것은 답에도 없어야 한다.**"""
    lines = []
    for i, it in enumerate(items, 1):
        serving = (f"1회 {it['serving_g']}g" if it.get("serving_g") else "1회 제공량 정보 없음")
        lines.append(
            f"{i}. [{it['code']}] {it['name']} ({it.get('category_big') or '분류 없음'}"
            f" / {it.get('maker') or '제조사 없음'})\n"
            f"   100g당 — 에너지 {fmt(it.get('energy_kcal'))}kcal ·"
            f" 나트륨 {fmt(it.get('sodium_mg'))}mg · 당류 {fmt(it.get('sugar_g'))}g\n"
            f"   {serving}"
        )
    return "\n".join(lines)


def fmt(value) -> str:
    """None을 0으로 바꾸지 않는다. 1회전의 결정이 프롬프트까지 온다."""
    return "정보없음" if value is None else f"{value:g}"


@router.post("/ask")
def ask(req: AskRequest) -> dict:
    items = search(req.q, req.limit, req.sodium_max)
    if not items:
        return {"q": req.q, "answer": "검색된 근거가 없어 답할 수 없습니다.", "sources": []}

    import litellm

    context = build_context(items)
    log.debug("SEMANTIC top-%d — 질의 임베딩 1회", len(items))
    for it in items:
        log.debug("  %s  %s  score %.4f", it["code"], it["name"], it["score"])
    log.debug("RAG CONTEXT (%d건):\n%s", len(items), context)
    res = litellm.completion(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"질문: {req.q}\n\n근거:\n{context}"},
        ],
    )
    usage = res.usage
    log.debug("ANSWER (%s) 입력 %d tok · 출력 %d tok\n%s",
              MODEL, usage.prompt_tokens, usage.completion_tokens,
              res.choices[0].message.content)
    # 키 이름은 **UI가 정한다.** ui/app.py는 v0.1에 고정돼 있고 input_tok ·
    # output_tok · cost_usd를 읽는다. 헤드리스 분리는 "UI를 안 바꾼다"가 아니라
    # "계약을 지킨다"는 뜻이다. 이름이 어긋나면 화면에 0이 뜨고, 그건 버그가
    # 아니라 계약 위반이라 조용히 지나간다
    return {
        "q": req.q,
        "answer": res.choices[0].message.content,
        # 근거를 함께 돌려준다. 답이 이상하면 이 코드로 원본 행을 조회해
        # 어디서 어긋났는지 추적할 수 있다 — 검색인지, 원본인지, LLM인지
        "sources": [{"code": it["code"], "name": it["name"],
                     "score": it["score"]} for it in items],
        "usage": {"input_tok": usage.prompt_tokens,
                  "output_tok": usage.completion_tokens,
                  "cost_usd": cost_of(res),
                  "model": MODEL},
    }


def cost_of(res) -> float:
    """LiteLLM이 모델별 요금표를 들고 있다. 우리가 단가를 박지 않는다."""
    try:
        import litellm

        return float(litellm.completion_cost(completion_response=res))
    except Exception:  # noqa: BLE001 — 요금표에 없는 모델이면 비용은 모른다
        return 0.0
