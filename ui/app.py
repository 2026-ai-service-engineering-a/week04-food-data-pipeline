"""가공식품 영양 탐색기 UI — Streamlit (사전 구축 자산).

오늘 이 파일은 한 줄도 안 건드린다. v0.1에서 v1.0까지 UI 코드는 그대로이고,
바뀌는 것은 API가 돌려주는 데이터뿐이다. **탭이 하나씩 살아나는 것**이 곧
파이프라인이 완성되는 과정이고, 그 장면이 이 시연의 뼈대다.
이것이 헤드리스 분리의 증명이다 (3주차와 같은 장면).

세 탭은 API의 세 계층에 1:1로 대응한다:
  검색      GET /foods           SQL     (2회전, 공짜)
  의미 검색  GET /foods/semantic  임베딩   (3회전, 싸다)
  질문      POST /ask            LLM     (3회전, 비싸다)
탭 순서가 곧 비용 사다리다.

탭은 처음부터 세 개 다 보인다. 아직 못 쓰는 탭도 "무엇을 할 자리인지"는
보여준다. 도착지를 모르고 걷는 것과 알고 걷는 것은 다르다.
"""

import os

import pandas as pd
import requests
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="가공식품 영양 탐색기", page_icon="🍜", layout="wide")


def api_get(path: str, **params):
    res = requests.get(f"{API_BASE_URL}{path}", params=params, timeout=120)
    res.raise_for_status()
    return res.json()


def api_post(path: str, payload: dict):
    res = requests.post(f"{API_BASE_URL}{path}", json=payload, timeout=120)
    res.raise_for_status()
    return res.json()


@st.cache_data(ttl=10, show_spinner=False)
def endpoint_alive(path: str, **params) -> bool:
    """그 회전이 왔는지는 엔드포인트가 답하는지로 안다.

    UI가 회전 번호를 알 필요는 없다. 있으면 쓰고 없으면 안내한다.
    """
    try:
        requests.get(f"{API_BASE_URL}{path}", params=params, timeout=10).raise_for_status()
        return True
    except requests.RequestException:
        return False


st.title("🍜 가공식품 영양 탐색기")
st.caption(
    "식약처 가공식품 DB 306,307건 — 정제된 데이터셋 위에 키워드 검색, 의미 검색, "
    "질의응답을 얹습니다. 두뇌는 전부 API에 있고 UI는 결과만 그립니다."
)

try:
    probe = api_get("/foods", limit=1)
except requests.RequestException as exc:
    st.error(f"API에 연결하지 못했습니다: {exc}")
    st.stop()

loaded = probe.get("total", 0)
has_search = loaded > 0
has_semantic = endpoint_alive("/foods/semantic", q="준비 확인", limit=1)
has_ask = endpoint_alive("/health") and has_semantic  # /ask는 의미 검색과 함께 온다

# ── 진행 상황: 무엇이 채워졌고 무엇이 남았나 ──────────────────────────
steps = [
    ("원본 엑셀", "scripts/download_file.py", None),
    ("정제 데이터셋", "1회전", None),
    ("섭취참고량 파싱", "1회전", None),
    ("PostgreSQL 적재", "2회전", has_search),
    ("벡터 인덱스", "3회전", has_semantic),
]
for i, stage in enumerate(probe.get("pipeline", [])):
    if i < 3:
        steps[i] = (stage["label"], stage["made_by"], stage["ready"])

done = sum(1 for _, _, ok in steps if ok)
st.progress(done / len(steps), text=f"파이프라인 {done}/{len(steps)} 단계 완료")
cols = st.columns(len(steps))
for col, (label, made_by, ok) in zip(cols, steps):
    # 이모지 대신 기하 문자를 쓴다. ⬜·◻️ 계열은 폰트에 따라 빈 네모로 깨진다
    col.markdown(f"{':green[●]' if ok else ':gray[○]'} **{label}**")
    col.caption(made_by)

if not has_search:
    st.info(
        probe.get("message", "데이터가 아직 없습니다")
        + " — 릴리즈 자산의 산출물을 받아 `data/` 아래에 풀면 이 화면이 채워집니다."
    )
    with st.expander("직접 만들려면: 회전별 명령"):
        st.code(
            "# 1) 원본 받기 (187MB — 레포 밖)\n"
            "docker compose exec api uv run python scripts/download_file.py\n\n"
            "# 2) 정제 + 섭취참고량 파싱 (1회전)\n"
            "docker compose exec api uv run python -m pipeline.clean \\\n"
            "  --input data/raw/가공식품DB.xlsx --output data/clean/foods_clean.parquet\n"
            "docker compose exec api uv run python -m pipeline.serving \\\n"
            "  --input data/clean/foods_clean.parquet\n\n"
            "# 3) PostgreSQL 적재 (2회전)\n"
            "docker compose exec api uv run python -m pipeline.load_pg \\\n"
            "  --input data/clean/foods_parsed.parquet\n\n"
            "# 4) 임베딩 인덱스 (3회전)\n"
            "docker compose exec api uv run python -m pipeline.embed_index",
            language="bash",
        )

st.divider()

# ── 세 탭은 처음부터 보인다. 못 쓰는 탭도 무엇을 할 자리인지는 알려준다 ──
tab_search, tab_semantic, tab_ask = st.tabs(
    ["🔎 검색 (SQL)", "🧭 의미 검색 (임베딩)", "💬 질문 (RAG)"]
)


def coming_soon(rotation: str, what: str, why: str, example: str) -> None:
    st.info(f"**{rotation}에서 살아나는 탭입니다.**")
    st.markdown(f"{what}\n\n{why}")
    st.caption("이런 질의를 받게 됩니다")
    st.code(example, language=None)


with tab_search:
    st.caption("이름·분류로 거르고 수치로 정렬합니다. LLM이 없는 층이라 공짜이고 즉시입니다.")
    if not has_search:
        coming_soon(
            "2회전",
            "정제된 30만 행을 PostgreSQL에 적재하고 `GET /foods`로 검색합니다.",
            "AI가 필요 없는 곳입니다. 조건이 명확한 질의는 SQL이 가장 빠르고 정확합니다.",
            '떡볶이 · 나트륨 낮은 순 · 당류 5g 이하',
        )
    else:
        col_q, col_sort = st.columns([3, 1])
        q = col_q.text_input("식품명 키워드", placeholder='예: "떡볶이"')
        sort = col_sort.selectbox(
            "정렬", ["sodium_asc", "sodium_desc", "energy_asc", "energy_desc", "sugar_asc"]
        )
        c1, c2, c3 = st.columns(3)
        sodium_max = c1.number_input("나트륨 상한 (mg/100g)", 0, 10000, 0, step=100)
        sugar_max = c2.number_input("당류 상한 (g/100g)", 0, 200, 0, step=5)
        energy_max = c3.number_input("열량 상한 (kcal/100g)", 0, 1000, 0, step=50)

        if st.button("검색", type="primary", use_container_width=True):
            params = {"q": q, "sort": sort, "limit": 50}
            for key, val in (("sodium_max", sodium_max), ("sugar_max", sugar_max),
                             ("energy_max", energy_max)):
                if val:
                    params[key] = val
            try:
                data = api_get("/foods", **params)
            except requests.RequestException as exc:
                st.error(f"검색 실패: {exc}")
            else:
                st.write(f"**{data['total']:,}건** 중 {len(data['items'])}건")
                if data["items"]:
                    st.dataframe(pd.DataFrame(data["items"]),
                                 use_container_width=True, hide_index=True)
                else:
                    st.info(
                        "0건입니다. 글자가 다르면 의미가 같아도 안 걸립니다 — "
                        "**의미 검색** 탭을 써보세요."
                    )

        st.divider()
        code = st.text_input("식품코드로 상세 보기", placeholder="예: P108-008000200-0095")
        if code:
            try:
                detail = api_get(f"/foods/{code}")
            except requests.RequestException as exc:
                st.error(f"조회 실패: {exc}")
            else:
                st.subheader(detail.get("name", code))
                left, right = st.columns(2)
                left.write("**100g 기준**")
                left.json(detail.get("per_100g", {}))
                right.write("**1회 제공량 기준**")
                per_serving = detail.get("per_serving") or {}
                if per_serving.get("serving_g") is None:
                    # 1회전의 정직한 NULL이 화면까지 그대로 온다 — 지어내지 않는다
                    right.warning(per_serving.get("note", "1회 제공량 정보 없음"))
                else:
                    right.json(per_serving)

with tab_semantic:
    st.caption("글자가 아니라 의미로 찾습니다. 질의 임베딩 한 번이라 사실상 공짜이고, LLM은 없습니다.")
    if not has_semantic:
        coming_soon(
            "3회전",
            "식품명과 분류를 한 문장으로 합쳐 벡터로 만들고, 질의도 벡터로 바꿔 가까운 것을 찾습니다.",
            "키워드 검색이 0건을 내는 질의가 여기서 답을 얻습니다. "
            "글자가 달라도 의미가 가까우면 걸립니다.",
            "매콤한 분식 간식",
        )
    else:
        sq = st.text_input("이런 걸 찾고 있어요", placeholder='예: "매콤한 분식 간식"')
        if st.button("의미로 찾기", use_container_width=True) and sq:
            try:
                data = api_get("/foods/semantic", q=sq, limit=10)
            except requests.RequestException as exc:
                st.error(f"의미 검색 실패: {exc}")
            else:
                st.dataframe(pd.DataFrame(data["items"]),
                             use_container_width=True, hide_index=True)

with tab_ask:
    st.caption(
        "검색이 추린 몇 건만 컨텍스트로 LLM에 넘깁니다. 30만 건이 아니라 5건입니다 — "
        "컨텍스트가 곧 비용입니다."
    )
    if not has_ask:
        coming_soon(
            "3회전",
            "의미 검색이 고른 top-5만 컨텍스트로 넣어 LLM이 문장으로 답합니다.",
            "30만 건은 컨텍스트에 안 들어갑니다. **다 주지 말고 찾아서 준다**가 RAG이고, "
            "근거로 쓴 제품 목록도 함께 돌려줍니다.",
            "나트륨이 낮은 매콤한 분식 간식 추천해줘",
        )
    else:
        question = st.text_input("질문", placeholder='예: "나트륨이 낮은 매콤한 분식 간식 추천해줘"')
        if st.button("물어보기", type="primary", use_container_width=True) and question:
            try:
                with st.spinner("검색 → 컨텍스트 조립 → 답변 생성…"):
                    data = api_post("/ask", {"q": question})
            except requests.RequestException as exc:
                st.error(f"질의 실패: {exc}")
            else:
                st.write(data.get("answer", ""))
                sources = data.get("sources") or []
                if sources:
                    # 근거 목록이 곧 검증 가능성이다. 답이 어느 행에서 왔는지 추적할 수 있어야 한다
                    st.caption("근거로 쓴 제품")
                    st.dataframe(pd.DataFrame(sources),
                                 use_container_width=True, hide_index=True)
                usage = data.get("usage") or {}
                if usage:
                    st.caption(
                        f"입력 {usage.get('input_tok', 0):,} tok · "
                        f"출력 {usage.get('output_tok', 0):,} tok · "
                        f"${usage.get('cost_usd', 0):.4f}"
                    )

with st.sidebar:
    st.header("이 화면의 구조")
    st.caption(
        "탭 순서가 비용 사다리입니다.\n\n"
        "**SQL** 공짜 → **임베딩** 싸다 → **LLM** 비싸다.\n\n"
        "싼 층에서 풀리는 문제를 비싼 층으로 가져가지 않는 것이 이번 주의 원칙입니다."
    )
    st.divider()
    st.caption(
        "UI 코드는 v0.1부터 v1.0까지 바뀌지 않습니다. "
        "탭이 하나씩 살아나는 것은 API가 채워지기 때문입니다."
    )
    st.caption(f"API: `{API_BASE_URL}`")
