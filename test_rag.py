import asyncio
import json
from pathlib import Path

from synora.db.session import AsyncSessionLocal
from synora.rag.engine import LegalRAGEngine
from synora.rag.ingester import DocumentIngester


async def main():
    async with AsyncSessionLocal() as session:
        ingester = DocumentIngester(session)
        engine = LegalRAGEngine(session)

        manifest_path = Path("data/kb_manifest.json")
        raw_dir = Path("data/raw")

        if manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            for filename, metadata in manifest.items():
                pdf_path = raw_dir / filename
                if not pdf_path.exists():
                    print(f"[SKIP] File not found: {filename}")
                    continue

                print(f"[INGEST] Processing {filename}...")
                try:
                    await ingester.ingest_pdf(str(pdf_path), metadata)
                    print(f"[OK] Done: {filename}")
                except Exception as e:
                    await session.rollback()
                    print(f"[ERROR] Failed on {filename}: {e}")
        else:
            print("[WARN] data/kb_manifest.json not found.")

        question = "What are the main principles of AI according to the UAE guidelines?"
        print(f"\nQuery: {question}")
        
        answer = await engine.query(question)
        print(f"\nResponse:\n{answer}")


if __name__ == "__main__":
    asyncio.run(main())