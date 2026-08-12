#!/bin/sh
# 회전 산출물을 릴리즈 자산 하나로 묶는다.
#
# 파일을 낱개로 올리면 브라우저로 받는 사람이 여러 번 클릭해야 하고, 하나를
# 빠뜨려도 조용히 실패한다. 받는 사람이 실수할 수 있는 방법은 적을수록 좋다.
#
# 아카이브 안의 경로는 **저장소 구조 그대로**다.
#   data/clean/…    data/dist/…    reports/…
# 아카이브를 열어 본 사람이 어디에 풀어야 하는지 바로 안다. 앞에서는 clean/과
# reports/를 나란히 뒀다가, 하나는 data/ 아래로 하나는 루트로 간다는 사실이
# 아카이브 어디에도 안 적혀 있어 고쳤다. **경로가 곧 설명이다.**
#
# 점으로 시작하는 파일명이 그대로 보존되는 것도 덤이다. GitHub 릴리즈는
# .serving_cache.json 같은 이름을 낱개로는 못 받는다.
#
# 사용법:
#   sh scripts/pack_release.sh v0.2
set -e

VERSION="${1:?사용법: sh scripts/pack_release.sh v0.2}"
OUT="dist/week04-${VERSION}-data.tar.gz"
STAGE=$(mktemp -d)

# 회전마다 산출물이 늘어나지만 받는 사람이 받을 파일은 늘 하나다.
# 누적으로 담는다 — v0.3부터 시작하는 사람이 v0.2 자산도 따로 받게 하면
# 그건 다운로드를 두 번 시키는 것이고, 한 번은 반드시 빠뜨린다.
mkdir -p dist "$STAGE/data/clean" "$STAGE/data/dist" "$STAGE/reports"

for f in data/clean/foods_clean.parquet data/clean/foods_parsed.parquet \
         data/clean/.serving_cache.json; do
  [ -f "$f" ] && cp "$f" "$STAGE/data/clean/" && echo "  + $f"
done
# 2회전 산출물. 덤프는 풀리는 자리가 data/dist/ 다 — 거기서 db-restore가
# 집어간다. 아카이브 경로가 곧 "어디에 두면 되는지"의 답이다
for f in dist/foods.dump; do
  [ -f "$f" ] && cp "$f" "$STAGE/data/dist/" && echo "  + $f"
done
# 리포트는 **그 실행이 실제로 찍은 것만** 싣는다. embed_report.txt는 인덱스를
# 직접 만든 사람의 산출물이라, 인덱스를 받아 쓰는 사람에게는 없는 게 맞다.
# 대신 조립안 A/B 프로브 결과는 싣는다 — 6-1절 판단의 근거다
for f in reports/clean_report.txt reports/parse_report.txt reports/rejected.csv \
         reports/embed_probe.txt reports/embed_probe_full.txt; do
  [ -f "$f" ] && cp "$f" "$STAGE/reports/" && echo "  + $f"
done

# macOS의 tar는 ._ 리소스포크를 끼워 넣는다. 받는 쪽에서 "이게 뭔가" 하게 만든다
COPYFILE_DISABLE=1 tar czf "$OUT" -C "$STAGE" data reports
rm -rf "$STAGE"

echo
echo "[pack] $OUT · $(du -h "$OUT" | cut -f1)"
echo "[pack] sha256 $(shasum -a 256 "$OUT" | cut -d' ' -f1)"
echo
echo "  gh release create $VERSION $OUT --title ... --notes ..."
