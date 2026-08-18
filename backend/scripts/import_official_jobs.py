"""导入用户从政府开放平台自行下载的岗位 CSV/JSON。"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Some Windows developer tools define a generic DEBUG=release variable.  It is
# unrelated to JobGuard and cannot be parsed as the application's boolean DEBUG
# setting, so ignore only invalid boolean values for this child process.
_debug_value = os.environ.get("DEBUG", "").strip().lower()
if _debug_value and _debug_value not in {"1", "0", "true", "false", "yes", "no", "on", "off"}:
    os.environ.pop("DEBUG", None)

from app.models.base import SessionLocal, engine
from app.services.beijing_job_api_service import beijing_job_api_service
from app.services.official_job_import_service import (
    BEIJING_HR_DATASET_URL,
    official_job_import_service,
)


def main() -> int:
    engine.echo = False
    parser = argparse.ArgumentParser(
        description="导入北京市人社局等政府平台合法下载的岗位数据，不负责登录或绕过验证码。"
    )
    parser.add_argument("file", type=Path, help="官方导出的 CSV、TXT 或 JSON 文件")
    parser.add_argument("--source-url", default=BEIJING_HR_DATASET_URL)
    parser.add_argument(
        "--computer-only",
        action="store_true",
        help="只保留计算机、软件、算法、数据、运维和信息安全等相关岗位",
    )
    parser.add_argument("--dry-run", action="store_true", help="只校验和预览，不写数据库")
    args = parser.parse_args()

    if not args.file.is_file():
        parser.error(f"文件不存在：{args.file}")

    records = official_job_import_service.load_file(args.file)
    if args.computer_only:
        records, filter_summary = beijing_job_api_service.filter_computer_jobs(records)
        print("计算机岗位筛选统计：")
        print(json.dumps(filter_summary, ensure_ascii=False, indent=2))
    print("预览：")
    print(json.dumps(official_job_import_service.preview(records), ensure_ascii=False, indent=2, default=str))
    db = SessionLocal()
    try:
        summary = official_job_import_service.import_records(
            db,
            records,
            source_url=args.source_url,
            dry_run=args.dry_run,
        )
        print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
        if args.dry_run:
            print("DRY RUN：未写入数据库。")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
