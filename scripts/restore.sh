#!/bin/sh
# 배포된 산출물을 제자리에 놓는다. compose의 data-restore 서비스가 이걸 돈다.
#
# 학생 입장에서는 이게 전부다:
#   1) 릴리즈에서 받은 파일을 data/dist/ 에 둔다
#   2) docker compose up
#
# 멱등하다. 이미 있으면 아무 것도 하지 않는다. 배포물이 없어도 조용히 나간다 —
# 정제를 직접 돌릴 사람에게는 없는 게 정상이고, "할 일이 없음"은 실패가 아니다.
#
# 회전이 서비스를 하나씩 더하듯 복원 대상도 하나씩 늘어난다.
#   1회전(지금)  foods_parsed.parquet  → data/clean/
#   2회전        foods.dump            → pg_restore (db 기동 후)
#   3회전        chroma_foods.tar.gz   → data/chroma/
set -e

DIST=/data/dist
CLEAN=/data/clean
say() { echo "[restore] $*"; }

mkdir -p "$CLEAN"
placed=0

# 회전 산출물 묶음. 아카이브 안의 경로가 풀리는 자리와 같게 만들어져 있어서
# 그냥 풀면 된다 (clean/… → data/clean/, reports/… → reports/).
# 낱개 파일보다 이쪽이 먼저다 — 받는 사람이 한 번만 받으면 되게.
for archive in "$DIST"/week04-*-data.tar.gz; do
  [ -f "$archive" ] || continue
  if [ -f "$CLEAN/foods_parsed.parquet" ] || [ -f "$CLEAN/foods_clean.parquet" ]; then
    say "$(basename "$archive") — 이미 풀려 있습니다"
    continue
  fi
  say "$(basename "$archive") 를 풉니다"
  tar xzf "$archive" -C /data
  # 리포트는 data/ 밖에 산다. 옮기고 나면 임시로 생긴 자리는 치운다
  if [ -d /data/reports ]; then
    [ -d /reports ] && cp -f /data/reports/* /reports/ 2>/dev/null
    rm -rf /data/reports
  fi
  say "완료 — clean/ 과 reports/ 에 놓았습니다"
  placed=$((placed + 1))
done

# 정제 산출물 — 파일만 옮기면 끝난다. 압축도 DB도 필요 없다
for name in foods_parsed.parquet foods_clean.parquet; do
  if [ -f "$DIST/$name" ]; then
    if [ -f "$CLEAN/$name" ]; then
      say "$name 이미 있습니다 — 건너뜁니다"
    else
      cp "$DIST/$name" "$CLEAN/$name"
      say "$name → data/clean/ ($(du -h "$CLEAN/$name" | cut -f1))"
      placed=$((placed + 1))
    fi
  fi
done

# 파싱 캐시가 함께 오면 같이 놓는다. 있으면 LLM을 한 번도 안 부른다.
#   이름을 둘 다 받는다. GitHub 릴리즈는 점으로 시작하는 파일명을 안 받아서
#   serving_cache.json으로 올라가고, 받는 쪽에서 이름을 바꾸게 하면 그건
#   "data/dist에 넣으면 된다"는 계약을 깨는 것이다. 받는 쪽이 아니라
#   여기가 흡수한다.
for src in "$DIST/.serving_cache.json" "$DIST/serving_cache.json"; do
  if [ -f "$src" ] && [ ! -f "$CLEAN/.serving_cache.json" ]; then
    cp "$src" "$CLEAN/.serving_cache.json"
    say "파싱 캐시도 함께 놓았습니다 — 재실행이 공짜입니다"
    placed=$((placed + 1))
  fi
done

if [ "$placed" -gt 0 ]; then
  say "완료 — $placed개 배치"
elif [ -f "$CLEAN/foods_parsed.parquet" ] || [ -f "$CLEAN/foods_clean.parquet" ]; then
  say "정제 산출물이 이미 있습니다"
else
  say "배포물이 없습니다. 직접 만들거나, 릴리즈에서 받아 data/dist/ 에 두세요."
  say "  직접: docker compose exec api uv run python -m pipeline.clean --input data/raw/<원본>.xlsx"
fi
