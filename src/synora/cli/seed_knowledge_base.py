import argparse
import asyncio
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import select

from synora.db.session import AsyncSessionLocal
from synora.models.document import Document
from synora.models.enums import DocumentDomain, DocumentType
from synora.rag.ingest import Ingestor

logger = structlog.get_logger(__name__)

# Default metadata mapping for the known UAE / international reference files.
# infer_metadata takes the first key found in the file name, so specific keys come first:
# Arabic editions before their English counterparts, and international instruments before
# generic words such as "ethics" that also appear in UAE file names.
KNOWN_METADATA: dict[str, dict[str, Any]] = {
    "unesco_ai_ethics_recommendation_ar": {
        "title": "توصية اليونسكو بشأن أخلاقيات الذكاء الاصطناعي (2021)",
        "domain": DocumentDomain.CROSS_DOMAIN.value,
        "doc_type": DocumentType.GUIDELINE.value,
        "country_code": "INT",
        "language": "ar",
    },
    "cabinet_resolution_65_2022_ar": {
        "title": (
            "قرار مجلس الوزراء رقم 65 لسنة 2022 "
            "بشأن اللائحة التنفيذية للمرسوم بقانون رقم 29 لسنة 2021"
        ),
        "domain": DocumentDomain.GOVERNMENT_SERVICES.value,
        "doc_type": DocumentType.REGULATION.value,
        "country_code": "AE",
        "language": "ar",
    },
    "pdpl_45_2021_ar": {
        "title": "مرسوم بقانون اتحادي رقم 45 لسنة 2021 بشأن حماية البيانات الشخصية (PDPL)",
        "domain": DocumentDomain.DATA_PROTECTION.value,
        "doc_type": DocumentType.LAW.value,
        "country_code": "AE",
        "language": "ar",
    },
    "29_2021_ar": {
        "title": "مرسوم بقانون اتحادي رقم 29 لسنة 2021 في شأن دخول وإقامة الأجانب",
        "domain": DocumentDomain.GOVERNMENT_SERVICES.value,
        "doc_type": DocumentType.LAW.value,
        "country_code": "AE",
        "language": "ar",
    },
    "unesco": {
        "title": "UNESCO Recommendation on the Ethics of Artificial Intelligence (2021)",
        "domain": DocumentDomain.CROSS_DOMAIN.value,
        "doc_type": DocumentType.GUIDELINE.value,
        "country_code": "INT",
        "language": "en",
    },
    "eu_ai_act": {
        "title": "EU Artificial Intelligence Act (Regulation (EU) 2024/1689)",
        "domain": DocumentDomain.CROSS_DOMAIN.value,
        "doc_type": DocumentType.REGULATION.value,
        "country_code": "EU",
        "language": "en",
    },
    "oecd": {
        "title": "OECD Recommendation of the Council on Artificial Intelligence (AI Principles)",
        "domain": DocumentDomain.CROSS_DOMAIN.value,
        "doc_type": DocumentType.GUIDELINE.value,
        "country_code": "INT",
        "language": "en",
    },
    "pdpl": {
        "title": "UAE Federal Decree-Law No. 45 of 2021 (PDPL)",
        "domain": DocumentDomain.DATA_PROTECTION.value,
        "doc_type": DocumentType.LAW.value,
        "country_code": "AE",
        "language": "en",
    },
    "strategy": {
        "title": "UAE National Strategy for Artificial Intelligence 2031",
        "domain": DocumentDomain.AI_GOVERNANCE.value,
        "doc_type": DocumentType.STRATEGY.value,
        "country_code": "AE",
        "language": "en",
    },
    "charter": {
        "title": "UAE Charter for the Development & Use of Artificial Intelligence",
        "domain": DocumentDomain.AI_GOVERNANCE.value,
        "doc_type": DocumentType.STRATEGY.value,
        "country_code": "AE",
        "language": "en",
    },
    "ai ready framework": {
        "title": "ITU AI Ready: Analysis Towards a Standardized Readiness Framework (Report 2.0)",
        "domain": DocumentDomain.CROSS_DOMAIN.value,
        "doc_type": DocumentType.REPORT.value,
        "country_code": "INT",
        "language": "en",
    },
    "3172": {
        "title": "ITU-T Y.3172 Architectural Framework for Machine Learning",
        "domain": DocumentDomain.CROSS_DOMAIN.value,
        "doc_type": DocumentType.STANDARD.value,
        "country_code": "INT",
        "language": "en",
    },
    "ethics": {
        "title": "UAE AI Ethics Guidelines",
        "domain": DocumentDomain.AI_GOVERNANCE.value,
        "doc_type": DocumentType.GUIDELINE.value,
        "country_code": "AE",
        "language": "en",
    },
    "65_2022": {
        "title": "UAE Cabinet Resolution No. 65 of 2022 (Executive Regulations)",
        "domain": DocumentDomain.GOVERNMENT_SERVICES.value,
        "doc_type": DocumentType.REGULATION.value,
        "country_code": "AE",
        "language": "en",
    },
    "29_2021": {
        "title": "UAE Federal Decree-Law No. 29 of 2021 on Entry and Residence of Foreigners",
        "domain": DocumentDomain.GOVERNMENT_SERVICES.value,
        "doc_type": DocumentType.LAW.value,
        "country_code": "AE",
        "language": "en",
    },
}


def infer_metadata(file_path: Path) -> dict[str, Any]:
    name_lower = file_path.stem.lower()
    for key, meta in KNOWN_METADATA.items():
        if key in name_lower:
            return {**meta, "source_uri": str(file_path)}

    return {
        "title": file_path.stem.replace("_", " ").replace("-", " ").title(),
        "source_uri": str(file_path),
        "country_code": "AE",
        "language": "en",
        "domain": DocumentDomain.CROSS_DOMAIN.value,
        "doc_type": DocumentType.OTHER.value,
    }


async def refresh_metadata(raw_dir: Path) -> None:
    """Correct title, language and classification of documents already ingested.

    Matches stored documents to files in ``raw_dir`` by file name, so mislabelled rows are
    fixed in place without re-extracting or re-embedding anything.
    """
    files = {p.name: p for p in raw_dir.iterdir() if p.is_file()}
    async with AsyncSessionLocal() as session:
        documents = (await session.execute(select(Document))).scalars().all()
        for doc in documents:
            path = files.get(Path(doc.source_uri or "").name)
            if path is None:
                logger.warning("seed_kb.refresh.no_file", title=doc.title, source=doc.source_uri)
                continue
            meta = infer_metadata(path)
            for field in ("title", "country_code", "language", "domain", "doc_type"):
                setattr(doc, field, meta[field])
            doc.source_uri = str(path)
            logger.info("seed_kb.refresh.updated", file=path.name, title=meta["title"])
        await session.commit()


async def seed_knowledge_base(raw_dir: Path) -> None:
    if not raw_dir.exists():
        logger.warning("seed_kb.directory_not_found", path=str(raw_dir))
        return

    ingestor = Ingestor()
    supported_exts = {".pdf", ".html", ".htm", ".txt"}
    files = sorted(
        p
        for p in raw_dir.iterdir()
        if p.is_file() and p.suffix.lower() in supported_exts and not p.name.endswith(".ocr.txt")
    )

    if not files:
        logger.warning("seed_kb.no_files_found", path=str(raw_dir))
        return

    logger.info("seed_kb.starting", file_count=len(files), path=str(raw_dir))

    for file_path in files:
        meta = infer_metadata(file_path)
        logger.info("seed_kb.ingesting_file", file=file_path.name, title=meta["title"])
        try:
            await ingestor.ingest_file(file_path, metadata=meta)
        except Exception as e:
            logger.error("seed_kb.ingest_failed", file=file_path.name, error=str(e))
            continue

    logger.info("seed_kb.completed", total_files=len(files))


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Synora knowledge base from raw documents.")
    parser.add_argument(
        "--path",
        type=str,
        default="data/knowledge_base/raw",
        help="Path to raw knowledge base documents directory.",
    )
    parser.add_argument(
        "--refresh-metadata",
        action="store_true",
        help="Only correct metadata of documents already ingested (no re-embedding).",
    )
    args = parser.parse_args()
    if args.refresh_metadata:
        asyncio.run(refresh_metadata(Path(args.path)))
    else:
        asyncio.run(seed_knowledge_base(Path(args.path)))


if __name__ == "__main__":
    main()
