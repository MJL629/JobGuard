"""
Resume Service

Orchestrates: RAG retrieval -> LLM generation -> MySQL storage -> PDF export
"""

import json
import logging
import os
import base64
import html
import re
import subprocess
from typing import Optional
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.resume import GeneratedResume
from app.agents.resume_generator import resume_generator
from app.services.profile_service import profile_service
from app.services.job_service import job_service
from app.services.resume_template_service import resume_template_service

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
        template_id = options.get("template_id", "template-01")
        if (
            resume_template_service.get_builtin(template_id) is None
            and resume_template_service.get_custom_path(user_id, template_id) is None
        ):
            return {"error": "所选简历模板不存在，请刷新模板列表后重试"}

        # 1. Get user profile
        user_profile = profile_service.get_full_profile(db, user_id)
        user_profile["user_id"] = user_id

        # 2. Get job info
        if job_id and not job_info:
            job_info = job_service.get_job_detail(db, job_id)
            if not job_info:
                return {"error": f"目标岗位不存在：{job_id}"}

        if not job_info:
            return {"error": "请先选择目标岗位"}

        # 3. Generate resume
        result = await resume_generator.generate(
            user_profile=user_profile,
            job_info=job_info,
            max_projects=max_projects,
        )

        if "error" in result:
            fallback_reason = result.get("error") or "模型生成未完成"
            result = {
                "resume_markdown": resume_generator._build_text_only_fallback_resume(
                    user_profile, job_info, fallback_reason
                ),
                "greeting": await resume_generator._generate_greeting(user_profile, job_info, []),
                "selected_projects": [],
                "self_evaluation": "",
                "output_mode": "text_only",
                "generation_warning": f"正式简历生成未完成，已降级输出可复制文本版和打招呼语。原因：{fallback_reason}",
                "fact_check": {
                    "verification_status": "text_only_fallback",
                    "has_fabrications": False,
                    "fabrications": [],
                    "confidence_score": 1.0,
                    "summary": "正式生成失败后触发文本兜底；兜底内容只使用已保存画像和目标岗位，不补写不可核验经历。",
                },
            }

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
            template_id=template_id,
            version=self._get_next_version(db, user_id, job_id),
        )
        db.add(resume)
        db.commit()
        db.refresh(resume)

        # 5. Generate editable DOCX and PDF for full document mode.  Text-only
        # fallback intentionally remains copy-first and never blocks the flow.
        output_mode = result.get("output_mode") or "document"
        docx_path = None
        pdf_path = None
        export_status = "skipped_text_only" if output_mode == "text_only" else "pending"
        if output_mode != "text_only":
            try:
                docx_path = resume_template_service.render_docx(
                    resume.id, result["resume_markdown"], template_id, user_id=user_id
                )
            except Exception as exc:
                logger.exception("[ResumeService] DOCX export failed: %s", exc)
            pdf_path = self._export_pdf(
                resume.id,
                result["resume_markdown"],
                template_id,
                docx_path=docx_path,
            )
            export_status = (
                "completed"
                if docx_path and pdf_path
                else "partial" if docx_path or pdf_path
                else "text_available_only"
            )
        resume.docx_path = docx_path
        resume.pdf_path = pdf_path
        db.commit()

        return {
            "resume_id": resume.id,
            "resume_markdown": result["resume_markdown"],
            "greeting": result.get("greeting", ""),
            "selected_projects": result.get("selected_projects", []),
            "self_evaluation": result.get("self_evaluation", ""),
            "pdf_path": pdf_path,
            "docx_path": docx_path,
            "template_id": template_id,
            "version": resume.version,
            "fact_check": result.get("fact_check", {}),
            "output_mode": output_mode,
            "generation_warning": result.get("generation_warning", ""),
            "export_status": export_status,
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
            "docx_path": resume.docx_path,
            "template_id": resume.template_id,
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
                "template_id": r.template_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in resumes
        ]

    def _export_pdf(
        self,
        resume_id: int,
        markdown: str,
        template_id: str = "template-01",
        docx_path: Optional[str] = None,
    ) -> Optional[str]:
        """Export resume Markdown to PDF"""
        try:
            os.makedirs(PDF_DIR, exist_ok=True)
            pdf_path = os.path.join(PDF_DIR, f"resume_{resume_id}_{template_id}.pdf")

            # Try weasyprint
            try:
                import markdown as md
                from weasyprint import HTML

                template_css = self._pdf_template_css(template_id)
                html_content = f"""
                <html>
                <head>
                    <meta charset="utf-8">
                    <style>
                        @page {{ size: A4; margin: 15mm 17mm; }}
                        body {{
                            color: #202124;
                            font-family: 'Microsoft YaHei', 'Noto Sans SC', Arial, sans-serif;
                            margin: 0 auto;
                            max-width: 176mm;
                        }}
                        h1 {{ font-size: 24px; margin: 0 0 5px; }}
                        h2 {{ font-size: 16px; margin: 18px 0 8px; page-break-after: avoid; }}
                        h3 {{ font-size: 14px; margin: 10px 0 3px; page-break-after: avoid; }}
                        p, li {{ font-size: 11px; line-height: 1.55; }}
                        p {{ margin: 4px 0; }}
                        ul {{ margin: 3px 0 7px; padding-left: 20px; }}
                        li {{ margin: 2px 0; }}
                        {template_css}
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

            except Exception as exc:
                logger.warning(
                    "[ResumeService] WeasyPrint unavailable (%s), trying portable PDF renderer",
                    type(exc).__name__,
                )
                if self._export_pdf_via_reportlab(markdown, pdf_path, template_id):
                    return pdf_path
                if docx_path and self._export_pdf_via_word(docx_path, pdf_path):
                    return pdf_path

                # Keep Markdown as a truthful fallback, but never label it as a PDF.
                md_path = os.path.join(PDF_DIR, f"resume_{resume_id}.md")
                with open(md_path, "w", encoding="utf-8") as f:
                    f.write(markdown)
                logger.info("[ResumeService] PDF unavailable; Markdown fallback saved: %s", md_path)
                return None

        except Exception as e:
            logger.error(f"[ResumeService] PDF export failed: {e}")
            return None

    @staticmethod
    def _export_pdf_via_reportlab(markdown: str, pdf_path: str, template_id: str) -> bool:
        """Render a portable Chinese PDF without GTK or an office installation."""
        try:
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_CENTER
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.cidfonts import UnicodeCIDFont
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

            font_name = "STSong-Light"
            try:
                pdfmetrics.getFont(font_name)
            except KeyError:
                pdfmetrics.registerFont(UnicodeCIDFont(font_name))

            accents = {
                "template-01": colors.HexColor("#4E7FA7"),
                "template-02": colors.HexColor("#444444"),
                "template-03": colors.HexColor("#222222"),
                "template-04": colors.HexColor("#AAA7D5"),
            }
            accent = accents.get(template_id, colors.HexColor("#333333"))
            styles = getSampleStyleSheet()
            normal = ParagraphStyle(
                "ResumeBody",
                parent=styles["BodyText"],
                fontName=font_name,
                fontSize=9.5,
                leading=14,
                textColor=colors.HexColor("#202124"),
                spaceAfter=2.5 * mm,
            )
            title = ParagraphStyle(
                "ResumeTitle",
                parent=normal,
                fontSize=22,
                leading=27,
                alignment=TA_CENTER if template_id == "template-02" else 0,
                textColor=accent,
                spaceAfter=4 * mm,
            )
            section = ParagraphStyle(
                "ResumeSection",
                parent=normal,
                fontSize=14,
                leading=18,
                textColor=colors.white if template_id in {"template-01", "template-04"} else accent,
                backColor=accent if template_id in {"template-01", "template-04"} else None,
                borderColor=accent,
                borderWidth=1 if template_id in {"template-02", "template-03"} else 0,
                borderPadding=4,
                spaceBefore=4 * mm,
                spaceAfter=2.5 * mm,
            )
            subheading = ParagraphStyle(
                "ResumeSubheading",
                parent=normal,
                fontSize=11.5,
                leading=15,
                textColor=accent,
                spaceBefore=2.5 * mm,
                spaceAfter=1.5 * mm,
            )
            bullet = ParagraphStyle(
                "ResumeBullet",
                parent=normal,
                leftIndent=5 * mm,
                firstLineIndent=-3 * mm,
                spaceAfter=1.2 * mm,
            )

            def inline_markup(value: str) -> str:
                escaped = html.escape(value.strip())
                escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
                escaped = re.sub(r"\*(.+?)\*", r"<i>\1</i>", escaped)
                return escaped

            story = []
            for raw_line in markdown.splitlines():
                line = raw_line.strip()
                if not line:
                    story.append(Spacer(1, 1.2 * mm))
                elif line.startswith("### "):
                    story.append(Paragraph(inline_markup(line[4:]), subheading))
                elif line.startswith("## "):
                    story.append(Paragraph(inline_markup(line[3:]), section))
                elif line.startswith("# "):
                    story.append(Paragraph(inline_markup(line[2:]), title))
                elif line.startswith(("- ", "* ")):
                    story.append(Paragraph("• " + inline_markup(line[2:]), bullet))
                else:
                    story.append(Paragraph(inline_markup(line), normal))

            document = SimpleDocTemplate(
                pdf_path,
                pagesize=A4,
                leftMargin=17 * mm,
                rightMargin=17 * mm,
                topMargin=15 * mm,
                bottomMargin=15 * mm,
                title="JobGuard 定向简历",
                author="JobGuard",
            )
            document.build(story)
            logger.info("[ResumeService] PDF exported through ReportLab: %s", pdf_path)
            return os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0
        except Exception as exc:
            logger.warning(
                "[ResumeService] ReportLab PDF fallback unavailable (%s)",
                type(exc).__name__,
            )
            return False

    @staticmethod
    def _export_pdf_via_word(docx_path: str, pdf_path: str) -> bool:
        """Use an installed Microsoft Word as a Windows-only PDF fallback."""
        if os.name != "nt" or not os.path.exists(docx_path):
            return False
        try:
            source = os.path.abspath(docx_path).replace("'", "''")
            target = os.path.abspath(pdf_path).replace("'", "''")
            script = f"""
$word = New-Object -ComObject Word.Application
try {{
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $doc = $word.Documents.Open('{source}', $false, $true)
    try {{ $doc.ExportAsFixedFormat('{target}', 17) }}
    finally {{ $doc.Close([ref]0) }}
}}
finally {{ $word.Quit() }}
"""
            encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-EncodedCommand",
                    encoded,
                ],
                check=False,
                timeout=75,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if completed.returncode != 0:
                logger.warning(
                    "[ResumeService] Word PDF converter exited with code %s",
                    completed.returncode,
                )
                return False
            logger.info("[ResumeService] PDF exported through Microsoft Word: %s", pdf_path)
            return os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0
        except Exception as exc:
            logger.warning(
                "[ResumeService] Word PDF fallback unavailable (%s)", type(exc).__name__
            )
            return False

    @staticmethod
    def _pdf_template_css(template_id: str) -> str:
        """Return a PDF style matching the selected built-in template family."""
        if template_id == "template-01":
            return """
                h1 { color: #315f82; }
                h2 { background: #4e7fa7; color: #fff; padding: 5px 9px; border: 0; }
                h3 { color: #315f82; }
            """
        if template_id == "template-02":
            return """
                body { border: 1px solid #444; padding: 10mm; }
                h1 { text-align: center; letter-spacing: 2px; }
                h2 { border: 1px solid #444; background: #ececec; padding: 4px 7px; }
                h3 { border-bottom: 1px dotted #777; padding-bottom: 3px; }
            """
        if template_id == "template-04":
            return """
                h1 { color: #67638e; }
                h2 { background: #aaa7d5; color: #fff; padding: 5px 9px; border: 0; }
                h3 { color: #67638e; }
            """
        return """
            h1 { letter-spacing: 1px; }
            h2 { border-top: 2px solid #222; border-bottom: 1px solid #555; padding: 5px 0; }
            h3 { border-bottom: 1px solid #bbb; padding-bottom: 3px; }
        """

    def _get_next_version(self, db: Session, user_id: int, job_id: Optional[int]) -> int:
        """Get next version number for a user+job combo"""
        query = db.query(GeneratedResume).filter(GeneratedResume.user_id == user_id)
        if job_id:
            query = query.filter(GeneratedResume.job_id == job_id)
        latest = query.order_by(GeneratedResume.version.desc()).first()
        return (latest.version + 1) if latest else 1


# Global singleton
resume_service = ResumeService()
