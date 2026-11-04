"""Export the knowledge base in the layout of the ITU AI Readiness reference code.

The ITU reference (github.com/CrashingGuru/ITUAIReadiness, simulation/server/knowledge) reads
documents from ``InputDocs/<category>/`` and stores chunks with the metadata fields
source_file, source_type, country, chunk_index, total_chunks, ingested_at and
document_category. This command writes:

- ``InputDocs/<category>/<file>``: the source documents, ready for the reference ``ingest.py``
- ``chunks.jsonl``: every indexed chunk with the reference metadata plus this project's
  article-level fields (title, section, page, language, domain, doc_type)
- ``manifest.json``: per-document coverage and the chunking and embedding settings

Usage: python -m synora.cli.export_kb --out /tmp/kb_export [--with-embeddings]
"""

import argparse
import asyncio
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from synora.config import settings
from synora.db.session import AsyncSessionLocal
from synora.models.document import Chunk, Document

# Reference source_type values: national strategies, laws and international reports.
NATIONAL_LEGAL_TYPES = {"law", "regulation"}


def category(doc: Document) -> str:
    """InputDocs sub-folder; the reference code stores it as document_category."""
    if doc.country_code != "AE":
        return "International_References"
    if doc.doc_type in NATIONAL_LEGAL_TYPES:
        return "UAE_Laws_Regulations"
    return "UAE_AI_Strategies"


def source_type(doc: Document) -> str:
    if doc.country_code == "AE":
        return "national_law" if doc.doc_type in NATIONAL_LEGAL_TYPES else "national_strategy"
    return "international_org_report"


def country(doc: Document) -> str:
    return {"AE": "United Arab Emirates", "EU": "European Union"}.get(doc.country_code, "global")


async def export(out: Path, with_embeddings: bool) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    exported_at = datetime.now(UTC).isoformat()
    async with AsyncSessionLocal() as session:
        docs = (await session.execute(select(Document).order_by(Document.title))).scalars().all()
        manifest_docs = []
        with (out / "chunks.jsonl").open("w", encoding="utf-8") as jsonl:
            for doc in docs:
                chunks = (
                    await session.execute(
                        select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.chunk_index)
                    )
                ).scalars().all()
                folder = category(doc)
                source = Path(doc.source_uri or "")
                if source.is_file():
                    target = out / "InputDocs" / folder / source.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                for chunk in chunks:
                    metadata = {
                        # Fields of the ITU reference ingest.build_metadata()
                        "source_file": source.name,
                        "source_type": source_type(doc),
                        "country": country(doc),
                        "chunk_index": str(chunk.chunk_index),
                        "total_chunks": str(len(chunks)),
                        "ingested_at": exported_at,
                        "document_category": folder,
                        # Article-level fields of this knowledge base
                        "title": doc.title,
                        "section": chunk.section or "",
                        "page": str((chunk.chunk_metadata or {}).get("page") or ""),
                        "language": doc.language,
                        "domain": str(doc.domain),
                        "doc_type": str(doc.doc_type),
                    }
                    record = {"id": str(chunk.id), "text": chunk.content, "metadata": metadata}
                    if with_embeddings:
                        record["embedding"] = [round(float(x), 6) for x in chunk.embedding]
                    jsonl.write(json.dumps(record, ensure_ascii=False) + "\n")
                manifest_docs.append(
                    {
                        "source_file": source.name,
                        "title": doc.title,
                        "document_category": folder,
                        "country": country(doc),
                        "language": doc.language,
                        "domain": str(doc.domain),
                        "doc_type": str(doc.doc_type),
                        "chunks": len(chunks),
                    }
                )

    manifest = {
        "exported_at": exported_at,
        "format": "ITU AI Readiness reference layout (InputDocs/<category>, chunk metadata)",
        "documents": manifest_docs,
        "totals": {
            "documents": len(manifest_docs),
            "chunks": sum(d["chunks"] for d in manifest_docs),
        },
        "chunking": {
            "unit": "article where the text has numbered articles, else heading or size",
            "chunk_size_chars": settings.rag_chunk_size,
            "chunk_overlap_chars": settings.rag_chunk_overlap,
        },
        "embedding": {
            "model": settings.ollama_embed_model,
            "dimensions": settings.embedding_dim,
            "included": with_embeddings,
        },
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest["totals"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default="/tmp/kb_export", help="Output directory.")
    parser.add_argument(
        "--with-embeddings", action="store_true", help="Include the bge-m3 vectors (larger)."
    )
    args = parser.parse_args()
    totals = asyncio.run(export(Path(args.out), args.with_embeddings))
    print(f"Exported {totals['documents']} documents and {totals['chunks']} chunks to {args.out}")


if __name__ == "__main__":
    main()
