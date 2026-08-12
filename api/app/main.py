"""가공식품 영양 탐색기 API — v0.1: 데이터가 아직 없는 뼈대.

이 저장소의 주인공은 API가 아니라 **데이터**다. 그래서 v0.1의 API는
"데이터가 없다"고 정직하게 말하는 것이 일이다. 회전이 돌면서 채워진다.

  1회전 feature/clean         정제 파이프라인 (pipeline/clean.py)
  2회전 feature/serving-parse 섭취참고량 파싱 (pipeline/serving_parse.py)
  3회전 feature/pg-service    PostgreSQL 적재 + GET /foods, GET /foods/{code}
  4회전 feature/rag-search    Chroma 인덱스 + GET /foods/semantic, POST /ask

헤드리스 구조: 이 API는 UI를 모른다. curl·Swagger(/docs)로 불러도 똑같이 동작한다.
"""

import os
from pathlib import Path

from fastapi import FastAPI

app = FastAPI(title="가공식품 영양 탐색기 API", version="0.1.0")

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))

# 파이프라인이 이 순서로 만들어 가는 산출물. v0.1에서는 넷 다 없다.
PIPELINE_STAGES = [
    ("raw", "원본 엑셀", DATA_DIR / "raw", "scripts/download_file.py"),
    ("clean", "정제 데이터셋", DATA_DIR / "clean" / "foods_clean.parquet", "1회전"),
    ("parsed", "섭취참고량 파싱", DATA_DIR / "clean" / "foods_parsed.parquet", "2회전"),
]


def pipeline_status() -> list[dict]:
    """어느 단계까지 와 있는지를 파일 존재로 판단한다.

    DB에 물어보지 않는 이유: v0.1에는 db 서비스 자체가 없다 (3회전이 추가한다).
    """
    status = []
    for key, label, path, made_by in PIPELINE_STAGES:
        ready = any(path.iterdir()) if path.is_dir() else path.exists()
        status.append({"stage": key, "label": label, "ready": ready, "made_by": made_by})
    return status


@app.get("/health")
def health() -> dict:
    """데이터가 없어도 /health는 뜬다 — 서비스 기동과 데이터 준비는 다른 문제다."""
    return {"status": "ok", "version": app.version}


@app.get("/foods")
def list_foods() -> dict:
    """v0.1 빈 상태 — 3회전에서 PostgreSQL 검색으로 교체된다."""
    return {
        "total": 0,
        "items": [],
        "message": "데이터가 아직 없습니다. README의 적재 절차를 따르세요",
        "pipeline": pipeline_status(),
    }
