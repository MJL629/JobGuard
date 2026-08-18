"""Deterministic company evidence storage and citation assembly.

The service deliberately separates a source record from a risk conclusion.  A
model response, a job description, or a user assertion can be stored as
reported evidence, but only allow-listed government hosts are marked verified.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from urllib.parse import urlsplit

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.company import Company, CompanyEvidence
from app.models.job import Job


class CompanyEvidenceError(ValueError):
    pass


class CompanyEvidenceService:
    OFFICIAL_HOSTS = (
        "gsxt.gov.cn",
        "samr.gov.cn",
        "gov.cn",
        "data.beijing.gov.cn",
        "court.gov.cn",
        "wenshu.court.gov.cn",
        "zxgk.court.gov.cn",
        "ggzy.gov.cn",
    )
    SOURCE_KINDS = {"official", "job_board", "media", "user_provided"}
    EVIDENCE_TYPES = {
        "registry",
        "operating_abnormality",
        "administrative_penalty",
        "social_insurance",
        "labor_dispute",
        "reputation",
        "official_job",
        "public_transaction",
        "other",
    }
    STRUCTURED_FIELDS = {
        "registry": {
            "registration_status",
            "unified_social_credit_code",
            "legal_representative",
            "registered_capital",
            "establishment_date",
            "address",
            "business_scope",
        },
        "operating_abnormality": {"abnormal_count", "status", "listed_at", "removed_at"},
        "administrative_penalty": {
            "penalty_count",
            "decision_number",
            "authority",
            "decision_date",
            "reason",
        },
        "social_insurance": {"participants", "reporting_year"},
        "labor_dispute": {"case_count", "case_number", "judgment_date", "cause"},
        "reputation": {"sentiment", "summary"},
        "official_job": {
            "job_id",
            "job_title",
            "location",
            "salary_min",
            "salary_max",
            "source_external_id",
            "published_at",
            "expires_at",
        },
        "public_transaction": {
            "transaction_count",
            "unified_social_credit_code",
            "legal_representative",
            "established_at",
        },
        "other": set(),
    }

    @staticmethod
    def normalize_company_name(value: str) -> str:
        value = str(value or "").strip()
        value = value.replace("(", "（").replace(")", "）")
        return re.sub(r"\s+", "", value)

    @classmethod
    def _host_is_official(cls, source_url: str) -> bool:
        host = (urlsplit(source_url).hostname or "").lower().rstrip(".")
        return any(host == item or host.endswith(f".{item}") for item in cls.OFFICIAL_HOSTS)

    @staticmethod
    def _validate_url(source_url: str) -> str:
        value = str(source_url or "").strip()
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise CompanyEvidenceError("来源链接必须是完整的 http/https 地址")
        return value

    @classmethod
    def _sanitize_structured_data(cls, evidence_type: str, value: dict | None) -> dict:
        if not isinstance(value, dict):
            return {}
        allowed = cls.STRUCTURED_FIELDS[evidence_type]
        return {key: item for key, item in value.items() if key in allowed and item is not None}

    @classmethod
    def _fingerprint(cls, payload: dict) -> str:
        canonical = {
            "company_name": cls.normalize_company_name(payload["company_name"]),
            "evidence_type": payload["evidence_type"],
            "source_url": payload["source_url"].strip(),
            "title": payload["title"].strip(),
        }
        return hashlib.sha256(
            json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def upsert_company(self, db: Session, company_name: str) -> Company:
        normalized = self.normalize_company_name(company_name)
        if not normalized:
            raise CompanyEvidenceError("企业名称不能为空")
        company = (
            db.query(Company)
            .filter(
                or_(
                    Company.name == str(company_name).strip(),
                    func.replace(Company.name, " ", "") == normalized,
                )
            )
            .first()
        )
        if company is None:
            company = Company(name=str(company_name).strip())
            db.add(company)
            db.flush()
        return company

    def add_evidence(
        self,
        db: Session,
        payload: dict,
        *,
        created_by_user_id: int | None = None,
    ) -> tuple[CompanyEvidence, bool]:
        company_name = str(payload.get("company_name") or "").strip()
        evidence_type = str(payload.get("evidence_type") or "").strip()
        source_kind = str(payload.get("source_kind") or "").strip()
        if evidence_type not in self.EVIDENCE_TYPES:
            raise CompanyEvidenceError("不支持的证据类型")
        if source_kind not in self.SOURCE_KINDS:
            raise CompanyEvidenceError("不支持的来源类型")
        source_url = self._validate_url(payload.get("source_url"))
        official_host = self._host_is_official(source_url)
        if source_kind == "official" and not official_host:
            raise CompanyEvidenceError("该域名不在官方来源白名单中，不能标记为官方证据")

        title = str(payload.get("title") or "").strip()
        source_name = str(payload.get("source_name") or "").strip()
        if not company_name or not title or not source_name:
            raise CompanyEvidenceError("企业名称、来源名称和证据标题不能为空")

        clean_payload = {
            **payload,
            "company_name": company_name,
            "evidence_type": evidence_type,
            "source_kind": source_kind,
            "source_url": source_url,
            "title": title,
        }
        source_hash = self._fingerprint(clean_payload)
        structured_data = self._sanitize_structured_data(
            evidence_type, payload.get("structured_data")
        )
        excerpt = str(payload.get("content_excerpt") or "").strip()[:5000] or None
        observed_at = payload.get("observed_at") or datetime.utcnow()
        published_at = payload.get("published_at")
        is_verified = source_kind == "official" and official_host

        company = self.upsert_company(db, company_name)
        evidence = (
            db.query(CompanyEvidence)
            .filter(CompanyEvidence.source_hash == source_hash)
            .first()
        )
        created = evidence is None
        if evidence is None:
            evidence = CompanyEvidence(source_hash=source_hash, company_id=company.id)
            db.add(evidence)

        evidence.company_id = company.id
        evidence.company_name = company_name
        evidence.evidence_type = evidence_type
        evidence.source_kind = source_kind
        evidence.source_name = source_name[:200]
        evidence.source_url = source_url[:1000]
        evidence.title = title[:300]
        evidence.content_excerpt = excerpt
        evidence.structured_data = structured_data
        evidence.is_verified = is_verified
        evidence.verification_level = "official" if is_verified else "reported"
        evidence.published_at = published_at
        evidence.observed_at = observed_at
        if created_by_user_id is not None:
            evidence.created_by_user_id = created_by_user_id
        company.last_checked = observed_at
        if is_verified:
            company.data_source = "verified_evidence"
        db.flush()
        return evidence, created

    def backfill_official_jobs(self, db: Session) -> dict:
        jobs = (
            db.query(Job)
            .filter(Job.source_type == "beijing_hr_open_data")
            .order_by(Job.id.asc())
            .all()
        )
        inserted = updated = linked = 0
        companies: set[int] = set()
        for job in jobs:
            company = self.upsert_company(db, job.company_name)
            companies.add(company.id)
            if job.company_id != company.id:
                job.company_id = company.id
                linked += 1
            evidence, created = self.add_evidence(
                db,
                {
                    "company_name": job.company_name,
                    "evidence_type": "official_job",
                    "source_kind": "official",
                    "source_name": "北京市公共数据开放平台",
                    "source_url": job.source_url,
                    "title": f"单位招聘岗位信息：{job.job_title}",
                    "content_excerpt": (job.jd_text or "")[:5000],
                    "structured_data": {
                        "job_id": job.id,
                        "job_title": job.job_title,
                        "location": job.location,
                        "salary_min": job.salary_min,
                        "salary_max": job.salary_max,
                        "source_external_id": job.source_external_id,
                        "published_at": job.source_published_at.isoformat()
                        if job.source_published_at
                        else None,
                        "expires_at": job.expires_at.isoformat() if job.expires_at else None,
                    },
                    "published_at": job.source_published_at,
                    "observed_at": job.last_seen_at or datetime.utcnow(),
                },
            )
            if created:
                inserted += 1
            else:
                updated += 1
        return {
            "jobs": len(jobs),
            "companies": len(companies),
            "evidence_inserted": inserted,
            "evidence_updated": updated,
            "jobs_linked": linked,
        }

    @staticmethod
    def _evidence_to_dict(evidence: CompanyEvidence) -> dict:
        return {
            "id": evidence.id,
            "company_id": evidence.company_id,
            "company_name": evidence.company_name,
            "evidence_type": evidence.evidence_type,
            "source_kind": evidence.source_kind,
            "source_name": evidence.source_name,
            "source_url": evidence.source_url,
            "title": evidence.title,
            "content_excerpt": evidence.content_excerpt,
            "structured_data": evidence.structured_data or {},
            "verification_level": evidence.verification_level,
            "is_verified": bool(evidence.is_verified),
            "published_at": evidence.published_at.isoformat() if evidence.published_at else None,
            "observed_at": evidence.observed_at.isoformat() if evidence.observed_at else None,
        }

    def search(self, db: Session, query: str, *, limit: int = 20) -> list[dict]:
        query = str(query or "").strip()
        if not query:
            return []
        companies = (
            db.query(Company)
            .filter(Company.name.contains(query))
            .order_by(Company.last_checked.desc(), Company.id.desc())
            .limit(limit)
            .all()
        )
        results = []
        for company in companies:
            evidence_count = (
                db.query(CompanyEvidence)
                .filter(CompanyEvidence.company_id == company.id)
                .count()
            )
            verified_count = (
                db.query(CompanyEvidence)
                .filter(
                    CompanyEvidence.company_id == company.id,
                    CompanyEvidence.is_verified.is_(True),
                )
                .count()
            )
            results.append(
                {
                    "id": company.id,
                    "name": company.name,
                    "evidence_count": evidence_count,
                    "verified_evidence_count": verified_count,
                    "last_checked": company.last_checked.isoformat()
                    if company.last_checked
                    else None,
                }
            )
        return results

    def get_company(self, db: Session, company_id: int) -> dict | None:
        company = db.query(Company).filter(Company.id == company_id).first()
        if company is None:
            return None
        summary = self.get_summary(db, company.name)
        return {
            "id": company.id,
            "name": company.name,
            "industry": company.industry,
            "scale": company.scale,
            "address": company.address,
            "description": company.description,
            "last_checked": company.last_checked.isoformat() if company.last_checked else None,
            **summary,
        }

    def get_summary(self, db: Session, company_name: str) -> dict:
        normalized = self.normalize_company_name(company_name)
        company = (
            db.query(Company)
            .filter(or_(Company.name == company_name, Company.name == normalized))
            .first()
        )
        if company is None:
            return {
                "verification_status": "unverified",
                "sources": [],
                "dimensions": {},
                "evidence": [],
            }
        evidence_rows = (
            db.query(CompanyEvidence)
            .filter(CompanyEvidence.company_id == company.id)
            .order_by(CompanyEvidence.observed_at.desc(), CompanyEvidence.id.desc())
            .all()
        )
        verified_rows = [item for item in evidence_rows if item.is_verified]
        dimensions = {
            "registry": self._dimension(verified_rows, {"registry"}),
            "business_risk": self._dimension(
                verified_rows, {"operating_abnormality", "administrative_penalty"}
            ),
            "social_insurance": self._dimension(verified_rows, {"social_insurance"}),
            "labor_disputes": self._dimension(verified_rows, {"labor_dispute"}),
            "official_jobs": self._dimension(verified_rows, {"official_job"}),
            "public_transactions": self._dimension(
                verified_rows, {"public_transaction"}
            ),
            "online_reputation": self._dimension(evidence_rows, {"reputation"}),
        }
        sources = [
            {
                "evidence_id": item.id,
                "title": item.title,
                "url": item.source_url,
                "source_name": item.source_name,
                "status": item.verification_level,
                "supports": item.evidence_type,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "observed_at": item.observed_at.isoformat() if item.observed_at else None,
            }
            for item in evidence_rows
        ]
        return {
            "verification_status": "official_evidence" if verified_rows else (
                "reported_evidence" if evidence_rows else "unverified"
            ),
            "sources": sources,
            "dimensions": dimensions,
            "evidence": [self._evidence_to_dict(item) for item in evidence_rows],
        }

    @staticmethod
    def _dimension(rows: list[CompanyEvidence], types: set[str]) -> dict:
        selected = [item for item in rows if item.evidence_type in types]
        merged: dict = {}
        for item in reversed(selected):
            merged.update(item.structured_data or {})
        return {
            "verified": any(item.is_verified for item in selected),
            "evidence_count": len(selected),
            "facts": merged,
            "evidence_ids": [item.id for item in selected],
        }


company_evidence_service = CompanyEvidenceService()
