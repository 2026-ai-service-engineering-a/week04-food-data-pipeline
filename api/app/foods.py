"""검색·상세 API — LLM이 없는 층.

조건이 명확한 질의는 SQL이 가장 빠르고 정확하다. "이름에 떡볶이가 들어간 것,
나트륨 낮은 순, 당류 5g 이하"에 AI를 부를 이유가 없다. **AI를 안 쓰는 결정도
설계다.**

3회전에서 이 판단이 뒤집히는 게 아니라 정교해진다. 글자가 아니라 의미로 물어야
하는 질의만 벡터 검색으로 가고, 그때도 답을 만드는 자리는 여기서 꺼낸 원본이다.

상세의 환산부가 1회전과 이어지는 지점이다. `serving_g`가 NULL이면 환산값도
NULL로 두고 원문을 함께 보인다. **모르는 것은 화면에서도 모른다고 나온다.**
"""

import json
import os

import psycopg
from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from app.status import pipeline_status

router = APIRouter(tags=["foods"])


def empty_state(message: str) -> dict:
    """v0.1이 돌려주던 것과 같은 모양.

    UI는 이 응답 하나로 "데이터가 있나"와 "어디까지 왔나"를 동시에 안다.
    회전이 바뀌어도 모양이 유지되므로 ui/app.py는 한 줄도 안 바뀐다.
    """
    return {"total": 0, "items": [], "message": message, "pipeline": pipeline_status()}

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@db:5432/food")

# 정렬은 화이트리스트로만 받는다. 문자열을 SQL에 이어 붙이는 자리라
# 사용자 입력이 그대로 들어가면 그게 곧 주입이다
#
# 값 하나만으로 정렬하면 **동점 사이 순서가 정해져 있지 않다.** 나트륨 0인
# 행만 27,219개라 동점은 예외가 아니라 기본이고, 순서가 매 질의마다 달라도
# 되는 것으로 취급되면 1페이지에 나온 행이 2페이지에 또 나온다. 실제로 그랬다.
# 그래서 마지막에 code를 붙여 **전순서**로 만든다 (SORT_TIEBREAK).
SORTS = {
    "sodium_asc": "sodium_mg asc nulls last",
    "sodium_desc": "sodium_mg desc nulls last",
    "sugar_asc": "sugar_g asc nulls last",
    "sugar_desc": "sugar_g desc nulls last",
    "energy_asc": "energy_kcal asc nulls last",
    "energy_desc": "energy_kcal desc nulls last",
    "name": "name asc",
}

# 모든 정렬의 마지막 키. 유일한 값이라 여기서 동점이 완전히 사라진다
SORT_TIEBREAK = "code asc"

NUTRIENTS = ["energy_kcal", "protein_g", "fat_g", "carb_g", "sugar_g", "sodium_mg",
             "saturated_fat_g", "trans_fat_g", "cholesterol_mg"]


def connect():
    """db 연결. 실패는 예외로 올린다 — 부르는 쪽이 상황에 맞게 처리한다."""
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def table_ready(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("select to_regclass('public.foods') is not null as ok")
        return bool(cur.fetchone()["ok"])


@router.get("/foods")
def search(
    q: str = Query("", description="식품명 부분 일치"),
    category: str = Query("", description="대분류"),
    sodium_max: float | None = None,
    sugar_max: float | None = None,
    energy_max: float | None = None,
    sort: str = Query("sodium_asc"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    """조건 조합 검색. 필터를 붙일 때마다 where에 한 줄씩 쌓는다."""
    if sort not in SORTS:
        raise HTTPException(400, f"sort는 {list(SORTS)} 중 하나")

    where, params = [], {}
    if q:
        where.append("name ilike %(q)s")
        params["q"] = f"%{q}%"
    if category:
        where.append("category_big = %(category)s")
        params["category"] = category
    for key, col in (("sodium_max", "sodium_mg"), ("sugar_max", "sugar_g"),
                     ("energy_max", "energy_kcal")):
        val = locals()[key]
        if val is not None:
            # 상한 필터는 NULL을 통과시키지 않는다. '모름'을 '이하'로 세면
            # 저나트륨 검색이 거짓말을 한다 — 1회전 NULL 정책의 연장이다
            where.append(f"{col} is not null and {col} <= %({key})s")
            params[key] = val

    clause = (" where " + " and ".join(where)) if where else ""
    try:
        conn = connect()
    except psycopg.Error:
        # db가 아직 없는 것은 오류가 아니라 **아직 그 회전이 안 온 것**이다.
        # v0.1과 같은 모양으로 답해야 UI가 코드 한 줄 안 바꾸고 계속 돈다
        return empty_state("db 서비스가 아직 없습니다. 2회전이 추가합니다")

    with conn:
        if not table_ready(conn):
            return empty_state("데이터가 아직 없습니다. README의 적재 절차를 따르세요")
        with conn.cursor() as cur:
            cur.execute(f"select count(*) as n from foods{clause}", params)
            total = cur.fetchone()["n"]
            cur.execute(
                f"select code, name, category_big, category_mid, maker,"
                f" energy_kcal, sodium_mg, sugar_g, serving_g, parse_method"
                f" from foods{clause} order by {SORTS[sort]}, {SORT_TIEBREAK}"
                f" limit %(limit)s offset %(offset)s",
                {**params, "limit": limit, "offset": offset},
            )
            items = cur.fetchall()
    return {"total": total, "items": items, "limit": limit, "offset": offset,
            "pipeline": pipeline_status()}


@router.get("/foods/{code}")
def detail(code: str) -> dict:
    """100g 기준과 1회 제공량 환산을 함께 준다."""
    try:
        conn = connect()
    except psycopg.Error as exc:
        raise HTTPException(503, f"db에 연결하지 못했습니다: {exc}") from exc
    with conn:
        if not table_ready(conn):
            raise HTTPException(503, "foods 테이블이 없습니다. pipeline.load_pg를 먼저 돌리세요")
        with conn.cursor() as cur:
            cur.execute("select * from foods where code = %(code)s", {"code": code})
            row = cur.fetchone()
    if row is None:
        raise HTTPException(404, f"식품코드를 찾지 못했습니다: {code}")

    per_100g = {c: row[c] for c in NUTRIENTS}
    grams = row["serving_g"]

    if grams is None:
        # 1회전의 정직한 NULL이 API 응답까지 그대로 온다. 지어내지 않는다
        per_serving = {
            "serving_g": None,
            "note": row["serving_note"] or f"1회 제공량 정보 없음 (원문: {row['serving_raw']!r})",
        }
    else:
        factor = grams / 100
        per_serving = {
            "serving_g": grams,
            "method": row["parse_method"],
            **{c: (None if per_100g[c] is None else round(per_100g[c] * factor, 1))
               for c in NUTRIENTS},
        }
        variants = json.loads(row["serving_variants"] or "[]")
        if variants:
            # 복합형은 대표값 하나로 줄지 않는다. 다른 형태로 먹으면 얼마인지도 보인다
            per_serving["variants"] = [
                {**v, **{c: (None if per_100g[c] is None else round(per_100g[c] * v["grams"] / 100, 1))
                         for c in ("sodium_mg", "energy_kcal")}}
                for v in variants
            ]
        if row["serving_note"]:
            per_serving["note"] = row["serving_note"]

    return {
        "code": row["code"], "name": row["name"],
        "category": {"big": row["category_big"], "mid": row["category_mid"],
                     "small": row["category_small"]},
        "maker": row["maker"], "package_weight": row["package_weight"],
        "per_100g": per_100g, "per_serving": per_serving,
    }
