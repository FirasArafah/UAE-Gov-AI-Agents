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

DEFAULT_RAW_DIR = "data/knowledge_base/raw"
# The text of this file comes out broken: split words and no article headings.
SKIPPED_FILES = {"UAE_Cabinet_Resolution_65_2022_AR.pdf"}

# Default metadata mapping for the known UAE / international reference files.
# infer_metadata takes the first key found in the file name, so specific keys come first:
# Arabic editions before their English counterparts, and international instruments before
# generic words such as "ethics" that also appear in UAE file names.
KNOWN_METADATA: dict[str, dict[str, Any]] = {
    "decree_law_14_2021_icp": {
        "title": (
            "UAE Federal Decree-Law No. 14 of 2021 Establishing the Authority for "
            "Identity, Citizenship, Customs and Ports Security"
        ),
        "domain": DocumentDomain.GOVERNMENT_SERVICES.value,
        "doc_type": DocumentType.LAW.value,
        "country_code": "AE",
        "language": "en",
    },
    "decree_law_44_2021_data_office": {
        "title": "UAE Federal Decree-Law No. 44 of 2021 Establishing the Emirates Data Office",
        "domain": DocumentDomain.DATA_PROTECTION.value,
        "doc_type": DocumentType.LAW.value,
        "country_code": "AE",
        "language": "en",
    },
    "decree_law_34_2021_cybercrime": {
        "title": "UAE Federal Decree-Law No. 34 of 2021 on Countering Rumors and Cybercrimes",
        "domain": DocumentDomain.NATIONAL_POLICY.value,
        "doc_type": DocumentType.LAW.value,
        "country_code": "AE",
        "language": "en",
    },
    "decree_law_34_2023_discrimination": {
        "title": (
            "UAE Federal Decree-Law No. 34 of 2023 on Combating Discrimination, Hatred "
            "and Extremism"
        ),
        "domain": DocumentDomain.CROSS_DOMAIN.value,
        "doc_type": DocumentType.LAW.value,
        "country_code": "AE",
        "language": "en",
    },
    "labour_law_33_2021": {
        "title": "UAE Federal Decree-Law No. 33 of 2021 on Employment Relationships (Labour Law)",
        "domain": DocumentDomain.NATIONAL_POLICY.value,
        "doc_type": DocumentType.LAW.value,
        "country_code": "AE",
        "language": "en",
    },
    "copyright_law_38_2021": {
        "title": "UAE Federal Decree-Law No. 38 of 2021 on Copyrights and Neighbouring Rights",
        "domain": DocumentDomain.NATIONAL_POLICY.value,
        "doc_type": DocumentType.LAW.value,
        "country_code": "AE",
        "language": "en",
    },
    "energy_strategy_2050": {
        "title": "UAE Energy Strategy 2050",
        "domain": DocumentDomain.NATIONAL_POLICY.value,
        "doc_type": DocumentType.STRATEGY.value,
        "country_code": "AE",
        "language": "en",
    },
    "digital_economy_strategy": {
        "title": "UAE Digital Economy Strategy",
        "domain": DocumentDomain.NATIONAL_POLICY.value,
        "doc_type": DocumentType.STRATEGY.value,
        "country_code": "AE",
        "language": "en",
    },
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
        "title": "OECD Recommendation of the Council on Artificial Intelligence (OECD/LEGAL/0449)",
        "domain": DocumentDomain.CROSS_DOMAIN.value,
        "doc_type": DocumentType.GUIDELINE.value,
        "country_code": "INT",
        "language": "en",
    },
    # Before "strategy", which would otherwise give these files the AI Strategy's title.
    "cybersecurity_strategy_2019_summary": {
        "title": "UAE National Cybersecurity Strategy 2019 (official summary, u.ae)",
        "domain": DocumentDomain.TELECOM.value,
        "doc_type": DocumentType.STRATEGY.value,
        "country_code": "AE",
        "language": "en",
    },
    "national_cybersecurity_strategy": {
        "title": "UAE National Cybersecurity Strategy 2019 (TDRA)",
        "domain": DocumentDomain.TELECOM.value,
        "doc_type": DocumentType.STRATEGY.value,
        "country_code": "AE",
        "language": "en",
    },
    "digital_government_strategy": {
        "title": "UAE Digital Government Strategy 2025",
        "domain": DocumentDomain.GOVERNMENT_SERVICES.value,
        "doc_type": DocumentType.STRATEGY.value,
        "country_code": "AE",
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


# Official page of each document, shown with its citations so a reader can check the source.
SOURCE_URLS: dict[str, str] = {
    "decree_law_14_2021_icp": "https://uaelegislation.gov.ae/en/legislations/2432",
    "decree_law_44_2021_data_office": "https://uaelegislation.gov.ae/en/legislations/2433",
    "decree_law_34_2021_cybercrime": "https://uaelegislation.gov.ae/en",
    "decree_law_34_2023_discrimination": "https://uaelegislation.gov.ae/en",
    "labour_law_33_2021": "https://faolex.fao.org/docs/pdf/uae217212E.pdf",
    "copyright_law_38_2021": "https://added.gov.ae/ipu/-/media/Files/Batch-3/copyright.pdf",
    "energy_strategy_2050": (
        "https://u.ae/en/about-the-uae/strategies-initiatives-and-awards/strategies-plans-and-visions/environment-and-energy/uae-energy-strategy-2050"
    ),
    "digital_economy_strategy": (
        "https://u.ae/en/about-the-uae/strategies-initiatives-and-awards/strategies-plans-and-visions/finance-and-economy/digital-economy-strategy"
    ),
    "unesco_ai_ethics_recommendation_ar": "https://unesdoc.unesco.org/ark:/48223/pf0000381137",
    "cabinet_resolution_65_2022_ar": "https://uaelegislation.gov.ae/ar/legislations/1601",
    "pdpl_45_2021_ar": "https://uaelegislation.gov.ae/ar/legislations/1972",
    "29_2021_ar": "https://uaelegislation.gov.ae/ar/legislations/1528",
    "unesco": "https://unesdoc.unesco.org/ark:/48223/pf0000381137",
    "eu_ai_act": "https://eur-lex.europa.eu/eli/reg/2024/1689/oj",
    "oecd": "https://legalinstruments.oecd.org/en/instruments/OECD-LEGAL-0449",
    "cybersecurity_strategy_2019_summary": (
        "https://u.ae/en/about-the-uae/strategies-initiatives-and-awards/strategies-plans-and-visions/strategies-plans-and-visions-untill-2021/national-cybersecurity-strategy-2019"
    ),
    "digital_government_strategy": (
        "https://u.ae/en/about-the-uae/strategies-initiatives-and-awards/strategies-plans-and-visions/government-services-and-digital-transformation/uae-national-digital-government-strategy"
    ),
    "pdpl": "https://uaelegislation.gov.ae/en/legislations/1972",
    "strategy": "https://ai.gov.ae/strategy/",
    "charter": (
        "https://uaelegislation.gov.ae/en/policy/details/the-uae-charter-for-the-development-and-use-of-artificial-intelligence"
    ),
    "ai ready framework": (
        "https://www.itu.int/dms_pub/itu-t/opb/ai4g/T-AI4G-AI4GOOD-2025-6-PDF-E.pdf"
    ),
    "3172": "https://www.itu.int/rec/T-REC-Y.3172/en",
    "ethics": "https://ai.gov.ae/wp-content/uploads/2023/03/MOCAI-AI-Ethics-EN-1.pdf",
    "65_2022": "https://uaelegislation.gov.ae/en/legislations/1601",
    "29_2021": "https://uaelegislation.gov.ae/en/legislations/1528",
}

def portal_page_metadata(file_path: Path) -> dict[str, Any]:
    """A page saved from the UAE government portal: its title, then its address, head the file."""
    lines = file_path.read_text(encoding="utf-8").splitlines()
    source_url = lines[2].removeprefix("Source: ").strip()
    return {
        "title": f"{lines[0].strip()} (UAE Government Portal)",
        "source_uri": str(file_path),
        "country_code": "AE",
        "language": "en",
        "domain": DocumentDomain.NATIONAL_POLICY.value,
        "doc_type": DocumentType.STRATEGY.value,
        "doc_metadata": {"source_url": source_url},
    }


def infer_metadata(file_path: Path) -> dict[str, Any]:
    name_lower = file_path.stem.lower()
    if name_lower.startswith("uae_portal_"):
        return portal_page_metadata(file_path)
    for key, meta in KNOWN_METADATA.items():
        if key in name_lower:
            source_url = SOURCE_URLS.get(key)
            return {
                **meta,
                "source_uri": str(file_path),
                "doc_metadata": {"source_url": source_url} if source_url else {},
            }

    return {
        "title": file_path.stem.replace("_", " ").replace("-", " ").title(),
        "source_uri": str(file_path),
        "country_code": "AE",
        "language": "en",
        "domain": DocumentDomain.CROSS_DOMAIN.value,
        "doc_type": DocumentType.OTHER.value,
    }


def find_seed_files(raw_dir: Path) -> list[Path]:
    supported_exts = {".pdf", ".html", ".htm", ".txt"}
    return sorted(
        p
        for p in raw_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() in supported_exts
        and not p.name.endswith(".ocr.txt")
        and p.name not in SKIPPED_FILES
    )


async def refresh_knowledge_base(raw_dir: Path) -> None:
    """Bring an existing knowledge base in line with the files and the current chunking.

    Corrects titles and classification, relabels chunks, drops documents whose file is gone or
    skipped, and ingests new files. Only text that changed is embedded again, so this is much
    faster than rebuilding the database.
    """
    files = {p.name: p for p in find_seed_files(raw_dir)}
    ingestor = Ingestor()
    async with AsyncSessionLocal() as session:
        documents = (await session.execute(select(Document))).scalars().all()
        stored = {}
        for doc in documents:
            name = Path(doc.source_uri or "").name
            path = files.get(name)
            if path is None:
                logger.warning("seed_kb.refresh.removed", title=doc.title, source=doc.source_uri)
                await session.delete(doc)
                continue
            meta = infer_metadata(path)
            for field in ("title", "country_code", "language", "domain", "doc_type"):
                setattr(doc, field, meta[field])
            doc.doc_metadata = meta["doc_metadata"]
            doc.source_uri = str(path)
            stored[name] = doc.id
        await session.commit()

    for name, path in sorted(files.items()):
        try:
            if name in stored:
                result = await ingestor.resync_document(stored[name], path)
                logger.info("seed_kb.refresh.updated", file=name, **result)
            else:
                logger.info("seed_kb.ingesting_file", file=name)
                await ingestor.ingest_file(path, metadata=infer_metadata(path))
        except Exception as e:
            logger.error("seed_kb.refresh_failed", file=name, error=str(e))


async def seed_knowledge_base(raw_dir: Path) -> None:
    if not raw_dir.exists():
        logger.warning("seed_kb.directory_not_found", path=str(raw_dir))
        return

    ingestor = Ingestor()
    files = find_seed_files(raw_dir)

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
        default=DEFAULT_RAW_DIR,
        help="Path to raw knowledge base documents directory.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Update an existing knowledge base, embedding only the text that changed.",
    )
    args = parser.parse_args()
    if args.refresh:
        asyncio.run(refresh_knowledge_base(Path(args.path)))
    else:
        asyncio.run(seed_knowledge_base(Path(args.path)))


if __name__ == "__main__":
    main()
