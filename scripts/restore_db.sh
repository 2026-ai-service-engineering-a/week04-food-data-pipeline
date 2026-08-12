#!/bin/sh
# 배포된 pg 덤프를 복원한다. compose의 db-restore 서비스가 이걸 돈다.
#
# parquet과 달리 덤프는 파일을 옮겨서 끝나지 않는다. PostgreSQL이 먼저 떠야
# 하고, 복원이 끝난 뒤에 api가 떠야 한다. 그래서 이 단계는 db가 healthy가
# 된 다음에 돌고, api는 이 단계가 끝나기를 기다린다.
#
# 멱등하다. 표가 이미 차 있으면 아무 것도 하지 않는다.
set -e

DUMP=/data/dist/foods.dump
say() { echo "[db-restore] $*"; }

rows=$(psql "$DATABASE_URL" -tAc \
  "select coalesce((select count(*) from foods), 0)" 2>/dev/null || echo 0)

if [ "${rows:-0}" -gt 0 ]; then
  say "foods 테이블에 이미 ${rows}행 있습니다 — 건너뜁니다"
elif [ -f "$DUMP" ]; then
  say "foods.dump 를 복원합니다"
  pg_restore -d "$DATABASE_URL" --clean --if-exists --no-owner "$DUMP"
  say "완료 — $(psql "$DATABASE_URL" -tAc 'select count(*) from foods')행"
else
  say "덤프가 없습니다. 직접 적재하거나 릴리즈에서 받아 data/dist/ 에 두세요."
  say "  직접: docker compose exec api uv run python -m pipeline.load_pg"
fi
