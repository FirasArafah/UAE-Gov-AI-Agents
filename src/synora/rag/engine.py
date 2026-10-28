from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from synora.rag.providers.factory import LLMProviderFactory
from synora.rag.vector_store import VectorStore


class LegalRAGEngine:
    """المحرك الأساسي الذي يربط كل المكونات ليجيب على أسئلة الـ Agents."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.vector_store = VectorStore(session)
        # استدعاء المصنع لتجهيز نموذج الذكاء الاصطناعي
        self.llm = LLMProviderFactory.create()

    async def query(self, question: str, domain_filter: Optional[str] = None) -> str:
        """
        يستقبل السؤال، يبحث عن القوانين المرتبطة، ويولد الإجابة الدقيقة.
        """
        # 1. تحويل السؤال إلى متجه (Embedding)
        query_embedding = await self.llm.embed_text(question)

        # 2. البحث عن أقرب النصوص القانونية (الفقرات) في قاعدة البيانات
        similar_results = await self.vector_store.search_similar_chunks(
            query_embedding=query_embedding,
            top_k=4,
            domain_filter=domain_filter
        )

        # 3. تجهيز السياق (Context) من النصوص المسترجعة
        context_texts = []
        for chunk, doc in similar_results:
            context_texts.append(f"مقتطف من قانون/وثيقة ({doc.title}):\n{chunk.content}")
        
        context = "\n\n".join(context_texts)

        # 4. بناء التعليمات للنموذج (System Prompt)
        system_prompt = (
            "أنت مستشار قانوني ذكي في نظام Synora، متخصص في قوانين وسياسات الذكاء الاصطناعي "
            "في الإمارات والمعايير العالمية. اعتمد فقط على المعلومات القانونية المرفقة للإجابة. "
            "إذا لم تكن الإجابة في السياق، اذكر ذلك بوضوح."
        )
        
        user_prompt = f"المعلومات القانونية المتاحة:\n{context}\n\nالسؤال: {question}"

        # 5. توليد الإجابة النهائية
        answer = await self.llm.generate_text(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.1
        )

        return answer