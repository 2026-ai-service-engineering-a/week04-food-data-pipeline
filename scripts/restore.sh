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
  # compose가 chroma 이미지를 고정하므로 보통은 어긋날 일이 없다.
  # 이미지를 올렸는데 옛 아카이브를 쓰는 경우만 여기 걸린다
  if ! grep -q "\"chroma_image\": \"${CHROMA_IMAGE}\"" /data/MANIFEST.json 2>/dev/null; then
    say "경고: 아카이브를 만든 chroma 버전이 compose의 버전과 다릅니다."
    say "      색인이 안 열리면 probe_vectors.tar.gz 를 받아 다시 적재하세요."
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
  say "  chroma_foods.tar.gz 를 data/dist/ 에 두고 다시 compose up 하면 됩니다"
fi
