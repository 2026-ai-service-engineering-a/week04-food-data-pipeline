"""파이프라인이 어디까지 왔나 — 파일 존재로 판단한다.

UI의 진행 막대가 이 값으로 그려진다. DB에 묻지 않는 이유는 단순하다.
v0.1에는 db 서비스 자체가 없고, 그래도 화면은 떠야 한다.

**진행 막대는 단조로워야 한다.** 뒷단계 산출물이 있는데 앞단계가 비어 있으면
그건 "덜 됐다"가 아니라 "그 단계를 남이 대신했다"는 뜻이다. 배포본으로 시작한
사람은 187MB 원본을 받을 일이 없어서, 파일 존재만 보면 원본 칸이 영원히
빈 동그라미로 남는다. 다 됐는데 4/5가 뜨는 화면은 사람을 헷갈리게 한다.
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


def _has_artifact(path: Path) -> bool:
    if path.is_dir():
        # .gitkeep은 "빈 디렉터리를 커밋하기 위한 표식"이지 데이터가 아니다
        return any(p for p in path.iterdir() if not p.name.startswith("."))
    return path.exists()


def pipeline_status() -> list[dict]:
    found = [_has_artifact(path) for _, _, path, _ in PIPELINE_STAGES]

    status = []
    for i, (key, label, _, made_by) in enumerate(PIPELINE_STAGES):
        # 뒤에 하나라도 산출물이 있으면 이 단계는 지난 것이다
        passed = any(found[i + 1:])
        status.append({
            "stage": key,
            "label": label,
            "ready": found[i] or passed,
            # 산출물이 없는데 지났다면 그 단계를 안 돌린 것이다. 그대로 적는다
            "made_by": made_by if found[i] else f"{made_by} (배포본)" if passed else made_by,
        })
    return status
