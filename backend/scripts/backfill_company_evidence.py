"""Create verifiable company/job evidence from already imported official jobs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models.base import SessionLocal  # noqa: E402
from app.services.company_evidence_service import company_evidence_service  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="将北京官方岗位转换为带来源链接的企业证据并关联 companies"
    )
    parser.add_argument("--dry-run", action="store_true", help="仅预览并回滚")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        summary = company_evidence_service.backfill_official_jobs(db)
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
        print(json.dumps({**summary, "dry_run": args.dry_run}, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        db.rollback()
        print(f"企业证据回填失败：{exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
