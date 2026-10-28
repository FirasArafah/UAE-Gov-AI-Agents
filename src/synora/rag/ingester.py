import hashlib
from pathlib import Path
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from pypdf import PdfReader

from synora.models.document import Document, Chunk
from synora.models.enums import DocumentDomain, DocumentType
from synora.rag.providers.factory import LLMProviderFactory

class DocumentIngester:
    """مسؤول عن قراءة الملفات، تقطيعها، تحويلها لمتجهات، وحفظها بقاعدة البيانات."""

    def __init__(self, session: AsyncSession):
        self.session = session
        # نستدعي المصنع ليجلب مزود الذكاء الاصطناعي (Ollama) لعمل الـ Embeddings
        self.llm = LLMProviderFactory.create()

    async def ingest_pdf(self, file_path: str, metadata: Dict[str, Any]):
        """قراءة ملف PDF وحفظه كمتجهات في الجداول المرتبطة."""
        path = Path(file_path)
        
        # 1. استخراج النص بالكامل من الـ PDF
        reader = PdfReader(path)
        full_text = "\n".join(page.extract_text() for page in reader.pages if page.extract_text())
            
        # إنشاء بصمة فريدة (Hash) لمنع تكرار رفع نفس الملف
        content_hash = hashlib.sha256(full_text.encode('utf-8')).hexdigest()
        
        # 2. حفظ بيانات الملف الأساسية في جدول Documents
        doc = Document(
            title=metadata.get("title", path.stem),
            domain=metadata.get("domain", DocumentDomain.CROSS_DOMAIN),
            doc_type=metadata.get("doc_type", DocumentType.OTHER),
            language=metadata.get("language", "ar"),
            content_hash=content_hash,
            raw_text=full_text
        )
        self.session.add(doc)
        await self.session.flush() # لجلب معرّف المستند (doc.id) قبل حفظ القطع

        # 3. تقطيع النص إلى فقرات (Chunks)
        chunk_size = 800
        chunks_text = [full_text[i:i + chunk_size] for i in range(0, len(full_text), chunk_size)]
        
        # 4. تحويل كل قطعة إلى متجه وحفظها في جدول Chunks
        for i, text_chunk in enumerate(chunks_text):
            embedding = await self.llm.embed_text(text_chunk) 
            
            chunk = Chunk(
                document_id=doc.id,
                chunk_index=i,
                content=text_chunk,
                embedding=embedding
            )
            self.session.add(chunk)
            
        await self.session.commit()
        return doc.id