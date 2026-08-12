#!/bin/sh
# 배포된 벡터 인덱스를 자동 복원한다. compose의 index-restore 서비스가 이걸 돈다.
#
# 학생 입장에서는 이게 전부다:
#   1) 받은 파일을 data/dist/ 에 둔다
#   2) docker compose up
#
# 멱등하다. 이미 복원돼 있으면 아무 것도 하지 않는다.
# 아카이브는 data/ 를 기준으로 풀리도록 포장돼 있다 (scripts/pack_dist.py 참고).
set -e

DIST=/data/dist
say() { echo "[restore] $*"; }

show_manifest() {
  [ -f /data/MANIFEST.json ] || return 0
  say "받은 인덱스 정보:"
  # jq 없이 읽는다. alpine에 없는 도구를 요구하지 않는다
  sed -n 's/.*"created": "\([^"]*\)".*/  만든 날짜: \1/p;
          s/.*"chroma_image": "\([^"]*\)".*/  chroma 버전: \1/p;
          s/.*"embedding_model": "\([^"]*\)".*/  임베딩 모델: \1/p' /data/MANIFEST.json | head -3
  if ! grep -q "\"chroma_image\": \"${CHROMA_IMAGE}\"" /data/MANIFEST.json 2>/dev/null; then
    say "경고: 아카이브가 만들어진 chroma 버전과 이 compose의 버전이 다를 수 있습니다."
    say "      색인이 안 열리면 probe_vectors.tar.gz 로 다시 받아 적재하세요."
  fi
}

if [ -f /data/chroma/chroma.sqlite3 ]; then
  say "chroma 인덱스가 이미 있습니다 — 건너뜁니다"
  show_manifest

elif [ -f "$DIST/chroma_foods.tar.gz" ]; then
  say "chroma_foods.tar.gz 를 풉니다 (몇 분 걸립니다)"
  tar xzf "$DIST/chroma_foods.tar.gz" -C /data
  say "완료 — 적재 없이 바로 씁니다"
  show_manifest

elif [ -f "$DIST/probe_vectors.tar.gz" ] && [ ! -f /data/clean/.probe_C.f32 ]; then
  say "probe_vectors.tar.gz 를 풉니다"
  tar xzf "$DIST/probe_vectors.tar.gz" -C /data
  say "완료 — index-load가 이어서 chroma에 적재합니다 (약 8분)"
  show_manifest

elif [ -f /data/clean/.probe_C.f32 ]; then
  say "벡터 파일이 있습니다 — index-load가 적재합니다"

else
  say "배포물이 없습니다. 의미 검색 없이 뜹니다."
  say "  받아서 쓰기: 릴리즈/Drive의 chroma_foods.tar.gz 를 data/dist/ 에 두고 다시 compose up"
  say "  직접 만들기: docker compose run --rm index-load (벡터 파일이 있을 때)"
fi
