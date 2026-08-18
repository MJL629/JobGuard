"""从北京市公共数据开放平台同步计算机相关岗位。"""

import argparse
import asyncio
import getpass
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.base import SessionLocal
from app.services.beijing_job_api_service import (
    BeijingJobAPIError,
    beijing_job_api_service,
)
from app.services.official_job_import_service import official_job_import_service


async def run(args) -> int:
    user_key = os.environ.get("BEIJING_DATA_USER_KEY", "").strip()
    if not user_key:
        user_key = getpass.getpass("请输入唯一标识码（输入不会显示，也不会保存）：").strip()
    if not user_key:
        print("未输入唯一标识码。", file=sys.stderr)
        return 2

    try:
        records = await beijing_job_api_service.fetch_all(
            user_key,
            page_size=args.page_size,
            max_pages=args.max_pages,
        )
    except BeijingJobAPIError as exc:
        print(f"接口同步失败：{exc}", file=sys.stderr)
        return 1
    finally:
        user_key = ""

    if beijing_job_api_service.transport_used == "edge":
        print("连接说明：站点拒绝标准 TLS 握手，已自动通过临时 Edge 无痕会话读取；会话现已关闭。")

    selected, filter_summary = beijing_job_api_service.filter_computer_jobs(records)
    print("计算机岗位筛选统计：")
    print(json.dumps(filter_summary, ensure_ascii=False, indent=2))
    print("标准化预览（最多 5 条）：")
    print(json.dumps(
        official_job_import_service.preview(selected, limit=5),
        ensure_ascii=False,
        indent=2,
        default=str,
    ))
    if not selected:
        print("没有筛选到计算机岗位，未写入数据库。", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        summary = official_job_import_service.import_records(
            db,
            selected,
            dry_run=not args.commit,
        )
    finally:
        db.close()
    print("数据库导入统计：")
    print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
    if args.commit:
        print("已写入 MySQL。")
    else:
        print("DRY RUN：未写入数据库。确认结果后增加 --commit 才会正式导入。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="分页读取北京人社岗位 API，只保留计算机相关岗位。默认 dry-run。"
    )
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--commit", action="store_true", help="确认后正式写入 MySQL")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
