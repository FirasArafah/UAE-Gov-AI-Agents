import asyncio

from synora.rag.retriever import PgVectorRetriever


async def main():
    r = PgVectorRetriever()
    for q in ["right to object to automated decision", "رفض طلبات التأشيرات"]:
        res = await r.search(q, top_k=3)
        print("\nQUERY:", q)
        for c in res:
            print(f"  {c['title']} | section={c['section']} | score={c['score']}")

asyncio.run(main())