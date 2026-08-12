"""임베딩 조립안 비교 — 무엇을 벡터로 만드느냐가 검색을 어떻게 바꾸는가.

같은 질의를 두 조립안에 던져 나란히 봅니다. 질의 임베딩은 한 번만 하고 양쪽에
같은 벡터를 씁니다. 그래야 차이가 조립안 때문이라고 말할 수 있습니다.

  A 식품명만          `부드러운식빵`
  C 식품명 + 분류      `부드러운식빵 · 과자류·빵류 또는 떡류 · 빵류`

메인 화면(app.py)은 시연 흐름 그대로 두고, 실험 도구는 이 페이지로 뺐습니다.
"""

import os

import pandas as pd
import requests
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="임베딩 조립안 비교", page_icon="🧪", layout="wide")

st.title("🧪 임베딩 조립안 비교")
st.caption(
    "검색 품질은 모델이 아니라 **무엇을 임베딩하느냐**에서 갈립니다. "
    "같은 질의를 두 조립안에 던져 그 차이를 눈으로 봅니다."
)

try:
    modes = requests.get(f"{API_BASE_URL}/probe/modes", timeout=30).json()
except requests.RequestException as exc:
    st.error(f"API에 연결하지 못했습니다: {exc}")
    st.stop()

ready = [m for m in modes["modes"] if m["ready"]]
if not ready:
    st.warning(
        "비교할 컬렉션이 비어 있습니다. 둘 중 하나를 하세요.\n\n"
        "1. 배포된 인덱스를 `data/dist/chroma_foods.tar.gz` 에 두고 `docker compose up`\n"
        "2. 벡터를 직접 뽑아 적재: `docker compose exec api uv run python "
        "scripts/embed_probe.py --input data/raw/<원본>.xlsx --variants A,C --workers 8` "
        "→ `docker compose run --rm index-load`"
    )
    st.stop()

cols = st.columns(len(ready) + 1)
cols[0].metric("벡터 저장소", modes.get("store", "chroma"))
for col, m in zip(cols[1:], ready):
    col.metric(f"{m['tag']} · {m['label']}", f"{m['count']:,}건")
st.caption(
    f"{modes['dim']}차원 · chroma 컬렉션 두 개 · HNSW 근사 검색(약 14ms). "
    "전수 비교(약 600ms)와 달리 **근사라서 상위 결과를 놓칠 수 있습니다** — "
    "recall@10이 80% 수준입니다."
)

st.divider()

PRESETS = [
    "매콤한 분식 간식",
    "나트륨 낮은 튀김 간식",
    "아이 간식으로 좋은 부드러운 빵",
    "더울 때 시원하게 마실 음료",
    "밥 대신 간단히 먹는 즉석식품",
]


def set_query(text: str) -> None:
    st.session_state.probe_q = text


if "probe_q" not in st.session_state:
    st.session_state.probe_q = PRESETS[3]

st.caption("교안에서 쓴 질의로 바로 재현해 보기")
preset_cols = st.columns(len(PRESETS))
for col, preset in zip(preset_cols, PRESETS):
    col.button(preset, use_container_width=True, on_click=set_query, args=(preset,))

col_q, col_k = st.columns([4, 1])
col_q.text_input("질의", key="probe_q", label_visibility="collapsed")
limit = col_k.number_input("결과 수", 3, 30, 5, label_visibility="collapsed")

if st.button("두 조립안에 던지기", type="primary", use_container_width=True):
    try:
        with st.spinner("질의 임베딩 1회 → 양쪽 전량 코사인…"):
            data = requests.get(
                f"{API_BASE_URL}/probe/compare",
                params={"q": st.session_state.probe_q, "limit": int(limit)},
                timeout=180,
            ).json()
    except requests.RequestException as exc:
        st.error(f"질의 실패: {exc}")
        st.stop()

    label = {m["mode"]: f"{m['tag']} · {m['label']}" for m in modes["modes"]}
    result_cols = st.columns(len(data["results"]))
    for col, (mode, items) in zip(result_cols, data["results"].items()):
        col.subheader(label.get(mode, mode))
        if isinstance(items, dict):
            col.error(items.get("error", "결과 없음"))
            continue
        # 대분류 집중도 — 결과가 한 부류로 모였는가. 작은 코퍼스에서는
        # 이 지표가 사람 판단과 어긋나므로 참고용으로만 본다
        bigs = [it["category_big"] for it in items]
        focus = max(bigs.count(b) for b in set(bigs)) / len(bigs) * 100
        col.caption(f"최고 {items[0]['score']:.3f} · 대분류 집중도 {focus:.0f}%")
        col.dataframe(
            pd.DataFrame([
                {
                    "점수": it["score"],
                    "식품명": it["name"],
                    "중분류": it["category_mid"],
                }
                for it in items
            ]),
            use_container_width=True,
            hide_index=True,
        )
        with col.expander("실제로 임베딩된 문장"):
            for it in items[:5]:
                st.code(it["embedded_text"], language=None)

    st.info(
        "**점수를 서로 비교하지 마세요.** 조립안이 다르면 텍스트 길이가 달라 "
        "유사도의 스케일 자체가 다릅니다. 짧은 텍스트일수록 점수가 높게 나옵니다. "
        "비교할 것은 점수가 아니라 **어떤 물건이 올라왔는가**입니다."
    )
    st.caption(
        "그리고 이 결과는 **근사**입니다. HNSW는 전수 비교가 아니라 그래프를 타고 "
        "내려가며 후보를 좁히므로, 진짜 1위를 놓치기도 합니다. 43배 빠른 대가입니다."
    )

with st.sidebar:
    st.header("보는 법")
    st.markdown(
        "- **이름만**은 글자가 맞으면 종류가 달라도 올립니다. "
        "`시원`(증류주)이 음료 질의에, `부드러운빵또아`(아이스크림)가 빵 질의에 걸립니다\n"
        "- **이름+분류**는 그 착오를 분류가 막습니다\n"
        "- 2회전에서 SQL이 `튀김`으로 튀김전용유를 물어온 실패와 같은 모양입니다"
    )
    st.divider()
    st.caption(f"API: `{API_BASE_URL}`")
