"""가공식품 영양 탐색기 UI — Streamlit (사전 구축 자산).

오늘 이 파일은 한 줄도 안 건드린다. v0.1에서 v1.0까지 UI 코드는 그대로이고,
바뀌는 것은 API가 돌려주는 데이터뿐이다. 빈 상태 화면이 검색 화면으로,
검색 화면이 질문 화면으로 바뀌는 순간이 곧 파이프라인이 완성되는 순간이다.
이것이 헤드리스 분리의 증명이다 (3주차와 같은 장면).

세 탭은 API의 세 계층에 1:1로 대응한다:
  검색  → GET /foods           SQL     (2회전, 공짜)
  의미 검색 → GET /foods/semantic 임베딩  (3회전, 싸다)
  질문  → POST /ask            LLM     (3회전, 비싸다)
탭 순서가 곧 비용 사다리다.
"""

import os

import pandas as pd
import requests
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
TIMEOUT = 120

st.set_page_config(page_title="가공식품 영양 탐색기", page_icon="🍜", layout="wide")


def api_get(path: str, **params):
    res = requests.get(f"{API_BASE_URL}{path}", params=params, timeout=TIMEOUT)
    res.raise_for_status()
    return res.json()


def api_post(path: str, payload: dict):
    res = requests.post(f"{API_BASE_URL}{path}", json=payload, timeout=TIMEOUT)
    res.raise_for_status()
    return res.json()


st.title("🍜 가공식품 영양 탐색기")
st.caption(
    "식약처 가공식품 DB 31만 건 — 정제된 데이터셋 위에 키워드 검색, 의미 검색, "
    "질의응답을 얹었습니다. 두뇌는 전부 API에 있고 UI는 결과만 그립니다."
)

# ── 빈 상태 관문 ──────────────────────────────────────────────────────
# /foods가 0건이면 아래 탭들은 그릴 것이 없다. 여기서 멈추고 절차를 안내한다.
try:
    probe = api_get("/foods", limit=1)
except requests.RequestException as exc:
    st.error(f"API에 연결하지 못했습니다: {exc}")
    st.stop()

if probe.get("total", 0) == 0:
    st.warning(probe.get("message", "데이터가 아직 없습니다"))
    st.subheader("데이터를 적재하세요")
    for stage in probe.get("pipeline", []):
        icon = "✅" if stage["ready"] else "⬜"
        st.write(f"{icon} **{stage['label']}** — {stage['made_by']}")
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
    st.info(
        "무거운 배치를 직접 돌리지 않아도 됩니다. 릴리즈 자산의 산출물을 받아 "
        "`data/` 아래에 풀면 이 화면이 곧바로 검색 화면으로 바뀝니다."
    )
    st.stop()

# ── 데이터가 있을 때: 검색 · 의미 검색 · 질문 ─────────────────────────
tab_search, tab_semantic, tab_ask = st.tabs(["🔎 검색 (SQL)", "🧭 의미 검색 (임베딩)", "💬 질문 (RAG)"])

with tab_search:
    st.caption("이름·분류로 거르고 수치로 정렬합니다. LLM이 없는 층이라 공짜이고 즉시입니다.")
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
        if sodium_max:
            params["sodium_max"] = sodium_max
        if sugar_max:
            params["sugar_max"] = sugar_max
        if energy_max:
            params["energy_max"] = energy_max
        try:
            data = api_get("/foods", **params)
        except requests.RequestException as exc:
            st.error(f"검색 실패: {exc}")
        else:
            st.write(f"**{data['total']:,}건** 중 {len(data['items'])}건")
            if data["items"]:
                st.dataframe(pd.DataFrame(data["items"]), use_container_width=True, hide_index=True)
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
    sq = st.text_input("이런 걸 찾고 있어요", placeholder='예: "매콤한 분식 간식"')
    if st.button("의미로 찾기", use_container_width=True) and sq:
        try:
            data = api_get("/foods/semantic", q=sq, limit=10)
        except requests.RequestException as exc:
            st.error(f"의미 검색 실패: {exc}")
        else:
            st.dataframe(pd.DataFrame(data["items"]), use_container_width=True, hide_index=True)

with tab_ask:
    st.caption(
        "검색이 추린 몇 건만 컨텍스트로 LLM에 넘깁니다. 31만 건이 아니라 5건입니다 — "
        "컨텍스트가 곧 비용입니다."
    )
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
                st.dataframe(pd.DataFrame(sources), use_container_width=True, hide_index=True)
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
    st.caption(f"API: `{API_BASE_URL}`")
