"""政府开放岗位数据的标准化与幂等导入。"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.models.job import Job

BEIJING_HR_DATASET_URL = (
    "https://data.beijing.gov.cn/zyml/ajg/srlsbj/"
    "466e22a6b0314b4298864dcfb1a50803.htm"
)


@dataclass
class ImportSummary:
    total: int = 0
    valid: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "valid": self.valid,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": self.errors[:20],
        }


class OfficialJobImportService:
    FIELD_ALIASES = {
        "company_name": ["单位名称", "招聘单位", "公司名称", "企业名称", "用人单位名称"],
        "job_title": ["岗位名称", "招聘岗位", "职位名称", "工种名称", "岗位"],
        "job_id": ["招聘岗位id", "招聘岗位ID", "岗位id", "岗位ID", "职位编号"],
        "salary_min": ["最低月薪", "月薪下限", "薪资下限", "最低工资"],
        "salary_max": ["最高月薪", "月薪上限", "薪资上限", "最高工资"],
        "salary_range": ["薪资范围", "工资范围", "薪酬范围", "薪资"],
        "location": ["工作地点", "工作地址", "所在区", "区县", "工作地区"],
        "education": ["文化程度", "学历要求", "最低学历"],
        "description": ["岗位描述", "职位描述", "岗位职责", "招聘条件", "岗位要求"],
        "posted_at": ["发布日期", "发布时间", "登记开始时间", "登记日期", "更新日期"],
        "expires_at": ["登记结束时间", "报名截止时间", "截止日期", "有效期至"],
        "headcount": ["（招聘）总人数", "招聘总人数", "招聘人数"],
        "employment_type": ["用工形式", "工作性质", "雇佣类型"],
    }

    def load_file(self, path: Path) -> list[dict]:
        content = path.read_bytes()
        suffix = path.suffix.lower()
        if suffix == ".json":
            data = json.loads(self._decode(content))
            if isinstance(data, dict):
                for key in ("data", "rows", "records", "items"):
                    if isinstance(data.get(key), list):
                        return data[key]
                return [data]
            if isinstance(data, list):
                return data
            raise ValueError("JSON 顶层必须是对象或数组")
        if suffix in {".csv", ".txt"}:
            text = self._decode(content)
            sample = text[:4096]
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
            except csv.Error:
                dialect = csv.excel
            return list(csv.DictReader(io.StringIO(text), dialect=dialect))
        raise ValueError("仅支持官方导出的 CSV、TXT 或 JSON 文件")

    def normalize_record(
        self,
        record: dict,
        source_url: str = BEIJING_HR_DATASET_URL,
        *,
        observed_at: datetime | None = None,
    ) -> dict | None:
        cleaned = {
            str(key).replace("\ufeff", "").strip(): value
            for key, value in (record or {}).items()
        }
        company_name = self._value(cleaned, "company_name")
        job_title = self._value(cleaned, "job_title")
        if not company_name or not job_title:
            return None

        external_id = self._value(cleaned, "job_id")
        fingerprint = hashlib.sha256(
            "|".join([company_name, job_title, self._value(cleaned, "location") or ""]).encode("utf-8")
        ).hexdigest()[:20]
        stable_external_id = (external_id or fingerprint)[:255]
        source_key = quote(external_id, safe="-_") if external_id else fingerprint
        education = self._value(cleaned, "education")
        description = self._value(cleaned, "description")
        employment_type = self._value(cleaned, "employment_type")
        headcount = self._value(cleaned, "headcount")
        salary_min = self._money(self._value(cleaned, "salary_min"))
        salary_max = self._money(self._value(cleaned, "salary_max"))
        if salary_min is None and salary_max is None:
            salary_min, salary_max = self._salary_range(self._value(cleaned, "salary_range"))
        requirements = []
        if education:
            requirements.append(f"学历要求：{education}")
        if description:
            requirements.extend(
                item.strip() for item in re.split(r"[\n；;]", description) if item.strip()
            )
        context_lines = []
        if employment_type:
            context_lines.append(f"用工形式：{employment_type}")
        if headcount:
            context_lines.append(f"招聘人数：{headcount}")
        if description:
            context_lines.append(description)

        category, sub_category = self._classify(job_title)
        source_published_at = self._date(self._value(cleaned, "posted_at"))
        expires_at = self._date(
            self._value(cleaned, "expires_at"),
            end_of_day=True,
        )
        return {
            "company_name": company_name[:200],
            "job_title": job_title[:200],
            "job_category": category,
            "sub_category": sub_category,
            "salary_min": salary_min,
            "salary_max": salary_max,
            "location": (self._value(cleaned, "location") or "北京")[:100],
            "jd_text": "\n".join(context_lines) or None,
            "requirements": list(dict.fromkeys(requirements)),
            "benefits": [],
            "source_url": f"{source_url}#job-{source_key}",
            "source_type": "beijing_hr_open_data",
            "source_external_id": stable_external_id,
            "source_published_at": source_published_at,
            "posted_at": source_published_at,
            "expires_at": expires_at,
            "last_seen_at": observed_at or datetime.utcnow(),
            "is_active": 1,
        }

    def import_records(
        self,
        db: Session,
        records: list[dict],
        *,
        source_url: str = BEIJING_HR_DATASET_URL,
        dry_run: bool = False,
        deactivate_expired: bool = False,
        deactivate_unseen: bool = False,
    ) -> ImportSummary:
        summary = ImportSummary(total=len(records))
        observed_at = datetime.utcnow()
        seen_external_ids: set[str] = set()
        normalized_records: list[tuple[int, dict]] = []
        for index, record in enumerate(records, 1):
            normalized = self.normalize_record(
                record,
                source_url,
                observed_at=observed_at,
            )
            if not normalized:
                summary.skipped += 1
                if len(summary.errors) < 20:
                    summary.errors.append(f"第 {index} 行缺少单位名称或岗位名称")
                continue
            if normalized["source_external_id"] in seen_external_ids:
                summary.skipped += 1
                continue
            seen_external_ids.add(normalized["source_external_id"])
            summary.valid += 1
            normalized_records.append((index, normalized))

        existing_by_external_id = {
            job.source_external_id: job
            for job in db.query(Job).filter(
                Job.source_type == "beijing_hr_open_data",
                Job.source_external_id.in_(seen_external_ids),
            ).all()
        } if seen_external_ids else {}
        existing_by_url = {
            job.source_url: job
            for job in db.query(Job).filter(
                Job.source_url.in_([item[1]["source_url"] for item in normalized_records])
            ).all()
        } if normalized_records else {}
        for _, normalized in normalized_records:
            existing = (
                existing_by_external_id.get(normalized["source_external_id"])
                or existing_by_url.get(normalized["source_url"])
            )
            if existing:
                summary.updated += 1
                if not dry_run:
                    for key, value in normalized.items():
                        setattr(existing, key, value)
            else:
                summary.inserted += 1
                if not dry_run:
                    db.add(Job(**normalized))
        if deactivate_expired:
            db.query(Job).filter(
                Job.source_type == "beijing_hr_open_data",
                Job.is_active == 1,
                Job.expires_at.isnot(None),
                Job.expires_at <= observed_at,
            ).update({Job.is_active: 0}, synchronize_session=False)
        if deactivate_unseen:
            unseen_query = db.query(Job).filter(
                Job.source_type == "beijing_hr_open_data",
                Job.source_url.like(f"{source_url}#job-%"),
                Job.source_external_id.isnot(None),
                Job.is_active == 1,
            )
            if seen_external_ids:
                unseen_query = unseen_query.filter(
                    ~Job.source_external_id.in_(seen_external_ids)
                )
            unseen_query.update({Job.is_active: 0}, synchronize_session=False)
        if dry_run:
            db.rollback()
        else:
            db.commit()
        return summary

    def preview(self, records: list[dict], limit: int = 5) -> list[dict]:
        return [
            normalized
            for record in records
            if (normalized := self.normalize_record(record))
        ][:limit]

    @classmethod
    def _value(cls, record: dict, field: str) -> str | None:
        for alias in cls.FIELD_ALIASES[field]:
            value = record.get(alias)
            if value is not None and str(value).strip() not in {"", "null", "None", "-"}:
                return str(value).strip()
        return None

    @staticmethod
    def _money(value: str | None) -> int | None:
        if not value:
            return None
        match = re.search(r"\d+(?:\.\d+)?", value.replace(",", ""))
        if not match:
            return None
        amount = float(match.group())
        if "万" in value:
            amount *= 10000
        elif "千" in value or "k" in value.lower():
            amount *= 1000
        return int(amount) if 0 < amount <= 1_000_000 else None

    @classmethod
    def _salary_range(cls, value: str | None) -> tuple[int | None, int | None]:
        if not value or any(label in value for label in ("面议", "时薪", "日薪")):
            return None, None
        numbers = re.findall(r"\d+(?:\.\d+)?", value.replace(",", ""))
        if not numbers:
            return None, None
        unit_multiplier = 10000 if "万" in value else (1000 if "千" in value or "k" in value.lower() else 1)
        amounts = [float(number) * unit_multiplier for number in numbers[-2:]]
        if len(amounts) == 1:
            amounts.append(amounts[0])
        if "年薪" in value:
            amounts = [amount / 12 for amount in amounts]
        normalized = [int(amount) if 0 < amount <= 1_000_000 else None for amount in amounts]
        return normalized[0], normalized[1]

    @staticmethod
    def _date(value: str | None, *, end_of_day: bool = False) -> datetime | None:
        if not value:
            return None
        normalized = value.strip().replace("年", "-").replace("月", "-").replace("日", "")
        has_explicit_time = bool(re.search(r"\d:\d", normalized))
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M",
            "%Y-%m-%d",
            "%Y/%m/%d",
            # Beijing HR CSV uses day/month/year (for example 15/5/2026).
            # Keep this before the US form so ambiguous values are interpreted
            # consistently with the official source.
            "%d/%m/%Y",
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y %H:%M",
            "%Y%m%d",
        ):
            try:
                parsed = datetime.strptime(normalized, fmt)
                if end_of_day and not has_explicit_time:
                    return parsed.replace(hour=23, minute=59, second=59)
                return parsed
            except ValueError:
                continue
        return None

    @staticmethod
    def _classify(title: str) -> tuple[str, str]:
        mappings = [
            (["前端", "web", "vue", "react"], "engineering", "前端开发"),
            (["后端", "java", "python", "服务端"], "engineering", "后端开发"),
            (["全栈", "软件开发", "软件工程师", "嵌入式", "客户端"], "engineering", "软件开发"),
            (["运维", "devops", "sre", "系统工程师", "网络工程师"], "engineering", "运维与系统"),
            (["算法", "机器学习", "大模型", "ai"], "algorithm", "AI算法"),
            (["数据分析", "数据运营", "数据开发", "数据工程", "数据库"], "product_data_testing", "数据分析"),
            (["测试", "质量"], "product_data_testing", "测试开发"),
            (["产品经理", "产品运营"], "product_data_testing", "产品经理"),
            (["安全", "风控"], "security", "网络安全"),
        ]
        lowered = title.lower()
        for keywords, category, sub_category in mappings:
            if any(keyword in lowered for keyword in keywords):
                return category, sub_category
        return "other", "其他"

    @staticmethod
    def _decode(content: bytes) -> str:
        for encoding in ("utf-8-sig", "gb18030"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise ValueError("文件编码无法识别，请导出为 UTF-8 CSV/JSON")


official_job_import_service = OfficialJobImportService()
