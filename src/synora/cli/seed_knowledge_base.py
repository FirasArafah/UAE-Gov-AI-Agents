import argparse
import asyncio
from pathlib import Path
from typing import Any

import structlog

from synora.models.enums import DocumentDomain, DocumentType
from synora.rag.ingest import Ingestor

logger = structlog.get_logger(__name__)

# Default metadata mapping for known UAE / reference files
KNOWN_METADATA: dict[str, dict[str, Any]] = {
    "pdpl": {
        "title": "UAE Federal Decree-Law No. 45 of 2021 (PDPL)",
        "domain": DocumentDomain.DATA_PROTECTION.value if hasattr(DocumentDomain, "DATA_PROTECTION") else "cross_domain",
        "doc_type": DocumentType.LAW.value if hasattr(DocumentType, "LAW") else "law",
        "country_code": "AE",
        "language": "en",
    },
    "strategy": {
        "title": "UAE National Strategy for Artificial Intelligence 2031",
        "domain": DocumentDomain.AI_GOVERNANCE.value if hasattr(DocumentDomain, "AI_GOVERNANCE") else "cross_domain",
        "doc_type": DocumentType.STRATEGY.value if hasattr(DocumentType, "STRATEGY") else "strategy",
        "country_code": "AE",
        "language": "en",
    },
    "charter": {
        "title": "UAE Charter for the Development & Use of Artificial Intelligence",
        "domain": DocumentDomain.AI_GOVERNANCE.value if hasattr(DocumentDomain, "AI_GOVERNANCE") else "cross_domain",
        "doc_type": DocumentType.POLICY.value if hasattr(DocumentType, "POLICY") else "policy",
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
        p for p in raw_dir.iterdir() if p.is_file() and p.suffix.lower() in supported_exts
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
    args = parser.parse_args()
    asyncio.run(seed_knowledge_base(Path(args.path)))


if __name__ == "__main__":
    main()