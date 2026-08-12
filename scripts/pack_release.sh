#!/bin/sh
# 회전 산출물을 릴리즈 자산 하나로 묶는다.
#
# 파일을 낱개로 올리면 브라우저로 받는 사람이 여러 번 클릭해야 하고, 하나를
# 빠뜨려도 조용히 실패한다. 받는 사람이 실수할 수 있는 방법은 적을수록 좋다.
#
# 아카이브 안의 경로는 풀리는 자리와 같게 맞춘다.
#   clean/…  → data/clean/     reports/…  → reports/
# 그래서 restore.sh가 경로를 해석할 필요 없이 그냥 풀면 된다.
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

mkdir -p dist "$STAGE/clean" "$STAGE/reports"

for f in data/clean/foods_clean.parquet data/clean/foods_parsed.parquet \
         data/clean/.serving_cache.json; do
  [ -f "$f" ] && cp "$f" "$STAGE/clean/" && echo "  + $f"
done
for f in reports/clean_report.txt reports/parse_report.txt reports/rejected.csv; do
  [ -f "$f" ] && cp "$f" "$STAGE/reports/" && echo "  + $f"
done

# macOS의 tar는 ._ 리소스포크를 끼워 넣는다. 받는 쪽에서 "이게 뭔가" 하게 만든다
COPYFILE_DISABLE=1 tar czf "$OUT" -C "$STAGE" clean reports
rm -rf "$STAGE"

echo
echo "[pack] $OUT · $(du -h "$OUT" | cut -f1)"
echo "[pack] sha256 $(shasum -a 256 "$OUT" | cut -d' ' -f1)"
echo
echo "  gh release create $VERSION $OUT --title ... --notes ..."
