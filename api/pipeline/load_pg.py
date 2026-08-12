"""3단계 적재 — 정제 데이터셋을 PostgreSQL로.

30만 행을 넣는 방법은 여럿이지만 값이 다르다. `INSERT`를 30만 번 부르면
왕복이 30만 번이고 커피를 마시고 와야 한다. `COPY`는 한 번의 스트림이다.
**규모가 커지면 "어떻게 넣는가"가 성능 요구사항이 된다.**

인덱스는 적재 **뒤에** 만든다. 먼저 만들면 행마다 트리를 갱신하느라 적재가
느려진다. 비어 있는 표에 붓고 그다음에 색인하는 것이 순서다.

사용법:
  uv run python -m pipeline.load_pg --input data/clean/foods_parsed.parquet
"""

import argparse
import io
import os
import sys
import time
from pathlib import Path

import pandas as pd

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@db:5432/food")

# parquet 컬럼 → 표 컬럼. 한글 컬럼명을 SQL에 그대로 쓰면 매번 따옴표를 붙여야
# 하고 오타가 조용히 지나간다. 경계에서 한 번 갈아탄다
COLUMNS = {
    "식품코드": "code",
    "식품명": "name",
    "식품대분류명": "category_big",
    "식품중분류명": "category_mid",
    "식품소분류명": "category_small",
    "제조사명": "maker",
    "에너지(kcal)": "energy_kcal",
    "단백질(g)": "protein_g",
    "지방(g)": "fat_g",
    "탄수화물(g)": "carb_g",
    "당류(g)": "sugar_g",
    "나트륨(mg)": "sodium_mg",
    "포화지방산(g)": "saturated_fat_g",
    "트랜스지방산(g)": "trans_fat_g",
    "콜레스테롤(mg)": "cholesterol_mg",
    "1회 섭취참고량": "serving_raw",
    "식품중량": "package_weight",
    "serving_g": "serving_g",
    "parse_method": "parse_method",
    "serving_note": "serving_note",
    "serving_variants": "serving_variants",
}

DDL = """
drop table if exists foods;
create table foods (
    code            text primary key,
    name            text not null,
    category_big    text,
    category_mid    text,
    category_small  text,
    maker           text,
    energy_kcal     double precision,
    protein_g       double precision,
    fat_g           double precision,
    carb_g          double precision,
    sugar_g         double precision,
    sodium_mg       double precision,
    saturated_fat_g double precision,
    trans_fat_g     double precision,
    cholesterol_mg  double precision,
    serving_raw     text,
    package_weight  text,
    serving_g       integer,
    parse_method    text,
    serving_note    text,
    serving_variants text
);
"""

# 검색이 30만 건에서 안 느린 이유가 이 다섯 줄이다.
#   pg_trgm은 '%떡볶이%' 같은 부분 일치를 색인으로 처리한다. 이게 없으면
#   이름 검색이 매번 전체 훑기가 된다
INDEXES = [
    "create extension if not exists pg_trgm",
    "create index foods_name_trgm on foods using gin (name gin_trgm_ops)",
    "create index foods_category_big on foods (category_big)",
    "create index foods_sodium on foods (sodium_mg)",
    "create index foods_sugar on foods (sugar_g)",
    "create index foods_energy on foods (energy_kcal)",
]


def copy_rows(conn, df: pd.DataFrame) -> None:
    """COPY 한 번으로 붓는다. INSERT 30만 번과 비교되는 지점."""
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False, na_rep="")
    buf.seek(0)
    cols = ", ".join(COLUMNS.values())
    with conn.cursor() as cur:
        with cur.copy(f"copy foods ({cols}) from stdin with (format csv, null '')") as cp:
            while chunk := buf.read(1 << 20):
                cp.write(chunk)


def main() -> int:
    ap = argparse.ArgumentParser(description="정제 데이터셋을 PostgreSQL에 적재")
    ap.add_argument("--input", default="data/clean/foods_parsed.parquet")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"입력이 없습니다: {src} — pipeline.serving을 먼저 돌리세요", file=sys.stderr)
        return 1

    import psycopg

    t0 = time.time()
    df = pd.read_parquet(src)
    missing = [c for c in COLUMNS if c not in df.columns]
    if missing:
        print(f"입력에 없는 컬럼: {missing}", file=sys.stderr)
        return 1
    df = df[list(COLUMNS)]
    print(f"[load ] {len(df):,}행 · {len(COLUMNS)}열 → {DATABASE_URL.rsplit('@', 1)[-1]}")

    with psycopg.connect(DATABASE_URL, autocommit=False) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
        conn.commit()

        copy_rows(conn, df)
        conn.commit()
        elapsed = time.time() - t0
        print(f"[copy ] {len(df):,}행 · {elapsed:.1f}초 · {len(df) / elapsed:,.0f}행/초")

        # 인덱스는 적재 뒤에. 먼저 만들면 행마다 트리를 갱신한다
        t1 = time.time()
        with conn.cursor() as cur:
            for sql in INDEXES:
                cur.execute(sql)
        conn.commit()
        print(f"[index] {len(INDEXES)}개 · {time.time() - t1:.1f}초")

        with conn.cursor() as cur:
            cur.execute("select count(*), count(serving_g) from foods")
            total, with_serving = cur.fetchone()
    print(f"[done ] foods {total:,}행 · serving_g 있는 행 {with_serving:,}"
          f" ({with_serving / total * 100:.1f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
