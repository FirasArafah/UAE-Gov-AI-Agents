from typing import List, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from synora.models.document import Chunk, Document

class VectorStore:
    """فئة للتعامل مع قاعدة بيانات PostgreSQL والبحث في المتجهات."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def search_similar_chunks(
        self,
        query_embedding: List[float],
        top_k: int = 5,
        domain_filter: Optional[str] = None
    ) -> List[Tuple[Chunk, Document]]:
        """
        البحث عن أقرب الفقرات المطابقة لمتجه السؤال باستخدام مسافة جيب التمام.
        """
        # بناء الاستعلام لربط جدول القطع (Chunks) بجدول المستندات (Documents)
        stmt = select(Chunk, Document).join(Document)
        
        # تصفية اختيارية حسب المجال (مثلاً: قوانين، اتصالات، صحة)
        if domain_filter:
            stmt = stmt.where(Document.domain == domain_filter)
        
        # ترتيب النتائج حسب الأقرب (Cosine Distance) باستخدام pgvector
        stmt = stmt.order_by(Chunk.embedding.cosine_distance(query_embedding)).limit(top_k)
        
        result = await self.session.execute(stmt)
        # إرجاع قائمة تحتوي على (القطعة، المستند الأصلي)
        return result.all()