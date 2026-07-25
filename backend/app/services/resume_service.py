"""
Resume Service

Orchestrates: RAG retrieval -> LLM generation -> MySQL storage -> PDF export
"""

import json
import logging
import os
from typing import Optional
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.resume import GeneratedResume
from app.agents.resume_generator import resume_generator
from app.services.profile_service import profile_service
from app.services.job_service import job_service

logger = logging.getLogger(__name__)

# PDF output directory
PDF_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "output", "resumes")


class ResumeService:
    """Resume generation service"""

    async def generate_resume(
        self,
        db: Session,
        user_id: int,
        job_id: Optional[int] = None,
        job_info: Optional[dict] = None,
        options: Optional[dict] = None,
    ) -> dict:
        """
        Generate a tailored resume.

        Args:
            db: DB session
            user_id: User ID
            job_id: Job ID (optional, if job already in DB)
            job_info: Job info dict (if job_id not provided)
            options: {max_projects, include_self_evaluation, generate_greeting}

        Returns:
            {resume_id, resume_markdown, greeting, selected_projects, self_evaluation}
        """
        options = options or {}
        max_projects = options.get("max_projects", 3)

        # 1. Get user profile
        user_profile = profile_service.get_full_profile(db, user_id)
        user_profile["user_id"] = user_id

        # 2. Get job info
        if job_id and not job_info:
            job_info = job_service.get_job_detail(db, job_id)
            if not job_info:
                return {"error": f"Job not found: {job_id}"}

        if not job_info:
            return {"error": "No job info provided"}

        # 3. Generate resume
        result = await resume_generator.generate(
            user_profile=user_profile,
            job_info=job_info,
            max_projects=max_projects,
        )

        if "error" in result:
            return result

        # 4. Save to DB
        resume = GeneratedResume(
            user_id=user_id,
            job_id=job_id,
            job_title=job_info.get("job_title", ""),
            company_name=job_info.get("company_name", ""),
            resume_markdown=result["resume_markdown"],
            greeting_text=result.get("greeting", ""),
            selected_projects=result.get("selected_projects", []),
            self_evaluation=result.get("self_evaluation", ""),
            version=self._get_next_version(db, user_id, job_id),
        )
        db.add(resume)
        db.commit()
        db.refresh(resume)

        # 5. Generate PDF
        pdf_path = self._export_pdf(resume.id, result["resume_markdown"])
        if pdf_path:
            resume.pdf_path = pdf_path
            db.commit()

        return {
            "resume_id": resume.id,
            "resume_markdown": result["resume_markdown"],
            "greeting": result.get("greeting", ""),
            "selected_projects": result.get("selected_projects", []),
            "self_evaluation": result.get("self_evaluation", ""),
            "pdf_path": pdf_path,
            "version": resume.version,
        }

    def get_resume(self, db: Session, resume_id: int) -> Optional[dict]:
        """Get a generated resume by ID"""
        resume = db.query(GeneratedResume).filter(GeneratedResume.id == resume_id).first()
        if not resume:
            return None

        return {
            "id": resume.id,
            "user_id": resume.user_id,
            "job_id": resume.job_id,
            "job_title": resume.job_title,
            "company_name": resume.company_name,
            "resume_markdown": resume.resume_markdown,
            "greeting_text": resume.greeting_text,
            "selected_projects": resume.selected_projects,
            "self_evaluation": resume.self_evaluation,
            "pdf_path": resume.pdf_path,
            "version": resume.version,
            "created_at": resume.created_at.isoformat() if resume.created_at else None,
        }

    def get_history(self, db: Session, user_id: int) -> list[dict]:
        """Get resume generation history for a user"""
        resumes = (
            db.query(GeneratedResume)
            .filter(GeneratedResume.user_id == user_id)
            .order_by(GeneratedResume.created_at.desc())
            .limit(50)
            .all()
        )

        return [
            {
                "id": r.id,
                "job_title": r.job_title,
                "company_name": r.company_name,
                "version": r.version,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in resumes
        ]

    def _export_pdf(self, resume_id: int, markdown: str) -> Optional[str]:
        """Export resume Markdown to PDF"""
        try:
            os.makedirs(PDF_DIR, exist_ok=True)
            pdf_path = os.path.join(PDF_DIR, f"resume_{resume_id}.pdf")

            # Try weasyprint
            try:
                import markdown as md
                from weasyprint import HTML

                html_content = f"""
                <html>
                <head>
                    <meta charset="utf-8">
                    <style>
                        body {{ font-family: 'Noto Sans SC', Arial, sans-serif; padding: 40px; max-width: 800px; margin: 0 auto; }}
                        h1 {{ font-size: 24px; margin-bottom: 4px; }}
                        h2 {{ font-size: 18px; border-bottom: 2px solid #333; padding-bottom: 4px; margin-top: 24px; }}
                        h3 {{ font-size: 15px; margin-bottom: 2px; }}
                        p, li {{ font-size: 13px; line-height: 1.6; }}
                        ul {{ margin-top: 2px; }}
                    </style>
                </head>
                <body>
                    {md.markdown(markdown)}
                </body>
                </html>
                """
                HTML(string=html_content).write_pdf(pdf_path)
                logger.info(f"[ResumeService] PDF exported: {pdf_path}")
                return pdf_path

            except ImportError:
                # Fallback: save as .md instead
                md_path = os.path.join(PDF_DIR, f"resume_{resume_id}.md")
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(markdown)
                logger.info(f"[ResumeService] Markdown saved (PDF lib not available): {md_path}")
                return md_path

        except Exception as e:
            logger.error(f"[ResumeService] PDF export failed: {e}")
            return None

    def _get_next_version(self, db: Session, user_id: int, job_id: Optional[int]) -> int:
        """Get next version number for a user+job combo"""
        query = db.query(GeneratedResume).filter(GeneratedResume.user_id == user_id)
        if job_id:
            query = query.filter(GeneratedResume.job_id == job_id)
        latest = query.order_by(GeneratedResume.version.desc()).first()
        return (latest.version + 1) if latest else 1


# Global singleton
resume_service = ResumeService()
