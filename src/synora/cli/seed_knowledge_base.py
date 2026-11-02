import argparse
import asyncio
from pathlib import Path
from typing import Any

import structlog

from synora.models.enums import DocumentDomain, DocumentType
from synora.rag.ingest import Ingestor

logger = structlog.get_logger(__name__)

# Default metadata mapping for all 8 known UAE / international reference files
KNOWN_METADATA: dict[str, dict[str, Any]] = {
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
        default="data/raw",
        help="Path to raw knowledge base documents directory.",
    )
    args = parser.parse_args()
    asyncio.run(seed_knowledge_base(Path(args.path)))


if __name__ == "__main__":
    main()
