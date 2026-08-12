"""K-FIND 가공식품 DB — Open-API 경로 (대안, 인증키 필요).

같은 데이터를 받는 두 번째 길이다. 기본 권장은 파일 다운로드(download_file.py)이고,
이쪽은 "API로 받으면 뭐가 다른가"를 보기 위한 대조군이다.

파일 경로와 다른 점:
  - 인증키가 필요하다 (식품안전나라 회원가입 후 발급)
  - 페이지네이션이다. 한 번에 최대 1,000건이라 31만 건이면 307번을 부른다
  - **09~19시에만 응답한다.** 새벽에 배치를 돌리려던 계획이 여기서 죽는다
  - 중간에 끊기면 처음부터가 아니라 이어 받아야 한다 (--start-page)

교훈은 마지막 두 줄에 있다. 외부 API에는 파일에 없는 제약이 붙는다.
"데이터를 어떻게 받을 것인가"가 아키텍처 결정인 이유다.

사용법:
  export FOODSAFETY_API_KEY=발급받은키
  uv run python scripts/download_api.py --out data/raw/foods_api.jsonl --max-pages 3
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

# 가공식품 영양성분 서비스. 서비스명은 포털 공지에 따라 바뀔 수 있다
SERVICE = "I2790"
ENDPOINT = "http://openapi.foodsafetykorea.go.kr/api"
PAGE_SIZE = 1000  # 이 API의 1회 최대치
SERVICE_HOURS = (9, 19)


def in_service_hours(now: datetime | None = None) -> bool:
    hour = (now or datetime.now()).hour
    return SERVICE_HOURS[0] <= hour < SERVICE_HOURS[1]


def fetch_page(key: str, start: int, end: int) -> dict:
    url = f"{ENDPOINT}/{urllib.parse.quote(key)}/{SERVICE}/json/{start}/{end}"
    with urllib.request.urlopen(url, timeout=60) as res:
        return json.load(res)


def main() -> int:
    parser = argparse.ArgumentParser(description="식품안전나라 Open-API로 가공식품 영양성분 수집")
    parser.add_argument("--out", default="data/raw/foods_api.jsonl")
    parser.add_argument("--start-page", type=int, default=1, help="이어받기 시작 페이지 (1부터)")
    parser.add_argument("--max-pages", type=int, default=0, help="0이면 끝까지")
    parser.add_argument("--sleep", type=float, default=0.5, help="호출 간 대기(초) — 예의")
    args = parser.parse_args()

    key = os.environ.get("FOODSAFETY_API_KEY", "").strip()
    if not key:
        print("FOODSAFETY_API_KEY가 없습니다.", file=sys.stderr)
        print("  발급: https://www.foodsafetykorea.go.kr/api/newUserApi.do", file=sys.stderr)
        print("  키 없이 원본이 필요하면 scripts/download_file.py (파일 경로)를 쓰세요.", file=sys.stderr)
        return 1

    if not in_service_hours():
        # 죽기 전에 왜 죽는지 말하는 것이 배치의 예의다
        print(f"지금은 서비스 시간이 아닙니다 (제공: {SERVICE_HOURS[0]}~{SERVICE_HOURS[1]}시).")
        print("이 제약이 파일 다운로드 경로를 기본으로 권장하는 이유입니다.")
        return 2

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    # 이어받기 — 중간에 끊겨도 처음부터가 아니다 (2회전 배치 안전장치의 예고편)
    mode = "a" if args.start_page > 1 and out.exists() else "w"

    total_written = 0
    page = args.start_page
    with out.open(mode, encoding="utf-8") as f:
        while True:
            start = (page - 1) * PAGE_SIZE + 1
            end = page * PAGE_SIZE
            payload = fetch_page(key, start, end)
            body = payload.get(SERVICE, {})
            result = body.get("RESULT", {})
            rows = body.get("row", [])

            if not rows:
                print(f"[api] page {page}: 0건 — 종료 ({result.get('MSG', '')})")
                break

            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            total_written += len(rows)
            total_count = body.get("total_count", "?")
            print(f"[api] page {page}: {len(rows):,}건 (누적 {total_written:,} / {total_count})")

            if len(rows) < PAGE_SIZE:
                break
            if args.max_pages and page - args.start_page + 1 >= args.max_pages:
                print(f"[api] --max-pages={args.max_pages} 도달 — 이어받기: --start-page {page + 1}")
                break
            page += 1
            time.sleep(args.sleep)

    print(f"[done] {total_written:,}행 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
