"""파이프라인이 어디까지 왔나 — 파일 존재로 판단한다.

UI의 진행 막대가 이 값으로 그려진다. DB에 묻지 않는 이유는 단순하다.
v0.1에는 db 서비스 자체가 없고, 그래도 화면은 떠야 한다.
"""

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))

# 파이프라인이 이 순서로 만들어 가는 산출물
PIPELINE_STAGES = [
    ("raw", "원본 엑셀", DATA_DIR / "raw", "scripts/download_file.py"),
    ("clean", "정제 데이터셋", DATA_DIR / "clean" / "foods_clean.parquet", "1회전"),
    ("parsed", "섭취참고량 파싱", DATA_DIR / "clean" / "foods_parsed.parquet", "1회전"),
]


def pipeline_status() -> list[dict]:
    status = []
    for key, label, path, made_by in PIPELINE_STAGES:
        if path.is_dir():
            # .gitkeep은 "빈 디렉터리를 커밋하기 위한 표식"이지 데이터가 아니다
            ready = any(p for p in path.iterdir() if not p.name.startswith("."))
        else:
            ready = path.exists()
        status.append({"stage": key, "label": label, "ready": ready, "made_by": made_by})
    return status
