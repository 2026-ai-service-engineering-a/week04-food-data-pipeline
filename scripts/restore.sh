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
#   2회전        foods.dump            → data/dist/ (db-restore가 이어받는다)
#   3회전        chroma_foods.tar.gz   → data/chroma/
set -e

DIST=/data/dist
CLEAN=/data/clean
say() { echo "[restore] $*"; }

mkdir -p "$CLEAN"
placed=0

# 회전 산출물 묶음. 아카이브 안이 저장소 구조 그대로라(data/clean/… reports/…)
# 어디로 가는지 아카이브를 열어보면 안다. 여기서는 그 경로대로 풀어 준다.
# 낱개 파일보다 이쪽이 먼저다 — 받는 사람이 한 번만 받으면 되게.
for archive in "$DIST"/week04-*-data.tar.gz; do
  [ -f "$archive" ] || continue
  # 회전마다 담긴 것이 다르다. 1회전은 parquet, 2회전은 덤프까지.
  # 무엇이 들었는지는 **아카이브에게 물어본다** — 버전을 코드에 박으면
  # 다음 회전마다 여기를 고쳐야 하고, 고치는 걸 잊으면 조용히 안 풀린다
  members=$(tar tzf "$archive")
  say "$(basename "$archive") 를 확인합니다"

  # 컨테이너에는 저장소 루트가 아니라 /data와 /reports가 따로 붙어 있다.
  # 앞의 한 칸씩을 벗겨 각자의 자리에 넣는다
  if echo "$members" | grep -q "^data/clean/" \
     && [ ! -f "$CLEAN/foods_parsed.parquet" ] && [ ! -f "$CLEAN/foods_clean.parquet" ]; then
    tar xzf "$archive" -C /data --strip-components=1 data/clean
    say "  data/clean/ 에 정제 산출물을 놓았습니다"
    placed=$((placed + 1))
  fi
  if echo "$members" | grep -q "^data/dist/foods.dump$" && [ ! -f "$DIST/foods.dump" ]; then
    tar xzf "$archive" -C /data --strip-components=1 data/dist
    say "  data/dist/foods.dump — db-restore가 이어받습니다"
    placed=$((placed + 1))
  fi
  if echo "$members" | grep -q "^reports/" && [ -d /reports ] \
     && [ ! -f /reports/clean_report.txt ]; then
    tar xzf "$archive" -C /reports --strip-components=1 reports
    say "  reports/ 에 리포트를 놓았습니다"
    placed=$((placed + 1))
  fi
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
