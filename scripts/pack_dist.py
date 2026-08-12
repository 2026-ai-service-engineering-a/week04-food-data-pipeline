"""배포물 포장 — 학생에게 줄 아카이브를 재현 가능하게 만든다.

손으로 tar를 말면 두 가지가 빠진다. **무엇이 들었는지**와 **어디에 맞는지**다.
받는 쪽에서 "이게 내 chroma 버전에 맞나?"를 물을 수 있어야 하므로 매니페스트를
아카이브 안에 함께 넣는다.

아카이브 두 가지:
  chroma_foods.tar.gz   컬렉션이 만들어진 상태 그대로. 풀면 끝 (빠름, 버전 결합 있음)
  probe_vectors.tar.gz  float32 벡터 원본. 적재가 필요 (느림, 버전 결합 없음)

두 아카이브 모두 압축을 풀면 data/ 아래에 정확히 들어가도록 경로를 맞춰 둔다.
  tar xzf chroma_foods.tar.gz -C data/   →  data/chroma/... + data/MANIFEST.json

사용법:
  docker compose stop chroma          # 스냅샷은 정지 상태에서 뜬다
  uv run python scripts/pack_dist.py
"""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(os.environ.get("DATA_DIR", "data"))
DIST = DATA / "dist"
CHROMA_DIR = DATA / "chroma"
CLEAN = DATA / "clean"

# 아카이브를 만든 환경. 받는 쪽이 자기 환경과 대조할 수 있어야 한다
CHROMA_IMAGE = os.environ.get("CHROMA_IMAGE", "chromadb/chroma:1.5.9")
DIM = int(os.environ.get("EMBEDDING_DIM", "768"))
HNSW = {"space": "cosine", "max_neighbors": 32, "ef_construction": 200, "ef_search": 200}

VECTOR_FILES = [".probe_A.f32", ".probe_C.f32", ".probe_A.done", ".probe_C.done",
                ".probe_source.parquet"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def collections() -> list[dict]:
    """sqlite에서 컬렉션 이름과 건수를 읽는다. chroma 서버가 꺼져 있어도 된다."""
    db_path = CHROMA_DIR / "chroma.sqlite3"
    if not db_path.exists():
        return []
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    out = []
    for cid, name in db.execute("select id, name from collections"):
        (count,) = db.execute(
            "select count(*) from embeddings e join segments s on e.segment_id = s.id "
            "where s.collection = ?", (cid,)
        ).fetchone()
        out.append({"name": name, "count": count})
    return sorted(out, key=lambda c: c["name"])


def manifest(kind: str) -> dict:
    return {
        "kind": kind,
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "식약처 가공식품 DB 20260728판 (306,307행)",
        "embedding_model": os.environ.get("EMBEDDING_MODEL", "gemini/gemini-embedding-001"),
        "dim": DIM,
        "hnsw": HNSW,
        "chroma_image": CHROMA_IMAGE,
        "collections": collections(),
        "note": "풀 때는 data/ 를 기준으로: tar xzf <archive> -C data/",
    }


def pack(name: str, kind: str, members: list[tuple[Path, str]]) -> Path | None:
    if not members:
        print(f"[skip] {name}: 넣을 것이 없습니다")
        return None
    DIST.mkdir(parents=True, exist_ok=True)
    out = DIST / name
    tmp_manifest = DIST / ".MANIFEST.json"
    tmp_manifest.write_text(json.dumps(manifest(kind), ensure_ascii=False, indent=1),
                            encoding="utf-8")
    print(f"[pack] {name} …")
    with tarfile.open(out, "w:gz") as tar:
        tar.add(tmp_manifest, arcname="MANIFEST.json")
        for src, arc in members:
            tar.add(src, arcname=arc)
    tmp_manifest.unlink()
    size = out.stat().st_size / 1024 ** 3
    print(f"[pack] {name} · {size:.2f}GB · sha256 {sha256(out)[:16]}…")
    return out


def main() -> int:
    if not CHROMA_DIR.exists() and not (CLEAN / ".probe_C.f32").exists():
        print("포장할 것이 없습니다. 인덱스를 먼저 만드세요.", file=sys.stderr)
        return 1

    made = []
    if (CHROMA_DIR / "chroma.sqlite3").exists():
        # chroma가 떠 있는 채로 뜨면 sqlite가 쓰는 중일 수 있다
        running = subprocess.run(
            ["sh", "-c", "docker compose ps --status running --services 2>/dev/null"],
            capture_output=True, text=True,
        ).stdout
        if "chroma" in running.split():
            print("경고: chroma가 실행 중입니다. `docker compose stop chroma` 후에 포장하세요.",
                  file=sys.stderr)
            return 1
        made.append(pack("chroma_foods.tar.gz", "chroma-index", [(CHROMA_DIR, "chroma")]))

    vectors = [(CLEAN / f, f"clean/{f}") for f in VECTOR_FILES if (CLEAN / f).exists()]
    if vectors:
        made.append(pack("probe_vectors.tar.gz", "raw-vectors", vectors))

    made = [m for m in made if m]
    index = {
        "manifest": manifest("dist-index"),
        "archives": [
            {"name": m.name, "bytes": m.stat().st_size, "sha256": sha256(m)} for m in made
        ],
    }
    (DIST / "MANIFEST.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n[done] 배포 준비 완료 — 아래를 Drive/릴리즈에 올리고 해시를 README에 적으세요")
    for a in index["archives"]:
        print(f"  {a['name']:<24} {a['bytes'] / 1024 ** 3:5.2f}GB  {a['sha256']}")
    print(f"  {'MANIFEST.json':<24} (아카이브 목록과 해시)")
    print(f"\n  총 디스크 여유 필요: {shutil.disk_usage(DIST).free / 1024 ** 3:.1f}GB 남음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
