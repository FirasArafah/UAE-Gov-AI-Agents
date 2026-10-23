import json
import pickle
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import faiss
import numpy as np
import pypdf
from sentence_transformers import SentenceTransformer

# ============================================================
# Paths & Configuration
# ============================================================
RAW_DIR = Path("data/raw")
MANIFEST_PATH = Path("data/kb_manifest.json")
KB_STORE_DIR = Path("kb_store")
INDEX_DIR = Path("data/index")

KB_STORE_DIR.mkdir(parents=True, exist_ok=True)
INDEX_DIR.mkdir(parents=True, exist_ok=True)

CONFIG = {
    "embedding_model_name": "sentence-transformers/all-MiniLM-L6-v2",
    "chunk_size": 800,
    "chunk_overlap": 120,
    "min_chunk_chars": 80,
}

# Fallback metadata if data/kb_manifest.json is not present
DEFAULT_DOCS_META = {
    "UAE_PDPL_45_2021.pdf": {
        "id": "DOC-001",
        "title": "Federal Decree-Law No. 45 of 2021 on the Protection of Personal Data",
        "source_url": "https://uaelegislation.gov.ae/en/legislations/1972",
        "source_type": "law",
        "kb_category": "uae_national",
        "domain": "data_protection",
        "jurisdiction": "UAE",
        "authority": "UAE Data Office",
    },
    "UAE_AI_Charter_2024.pdf": {
        "id": "DOC-002",
        "title": "UAE Charter for the Development and Use of Artificial Intelligence (2024)",
        "source_url": "https://uaelegislation.gov.ae/en/policy/details/the-uae-charter-for-the-development-and-use-of-artificial-intelligence",
        "source_type": "policy",
        "kb_category": "uae_national",
        "domain": "ai_governance",
        "jurisdiction": "UAE",
        "authority": "UAE Cabinet / AI Office",
    },
    "UAE_National_AI_Strategy_2031.pdf": {
        "id": "DOC-003",
        "title": "UAE National Strategy for Artificial Intelligence 2031",
        "source_url": "https://u.ae/en/about-the-uae/strategies-initiatives-and-awards/strategies-plans-and-visions/government-services-and-digital-transformation/uae-strategy-for-artificial-intelligence",
        "source_type": "strategy",
        "kb_category": "uae_national",
        "domain": "ai_governance",
        "jurisdiction": "UAE",
        "authority": "Minister of State for Artificial Intelligence",
    },
    "UAE_AI_Ethics_Guidelines.pdf": {
        "id": "DOC-004",
        "title": "UAE AI Ethics Principles and Guidelines",
        "source_url": "https://u.ae/en/about-the-uae/digital-uae/digital-technology/artificial-intelligence/ai-resources",
        "source_type": "guideline",
        "kb_category": "uae_national",
        "domain": "ai_ethics",
        "jurisdiction": "UAE",
        "authority": "UAE Council for Artificial Intelligence and Blockchain",
    },
    "UAE_Decree_Law_29_2021_Entry_Residence.pdf": {
        "id": "DOC-005",
        "title": "Federal Decree-Law No. 29 of 2021 Concerning the Entry and Residence of Foreigners",
        "source_url": "https://uaelegislation.gov.ae/en/legislations/1528",
        "source_type": "law",
        "kb_category": "uae_national",
        "domain": "public_services_residency",
        "jurisdiction": "UAE",
        "authority": "Federal Authority for Identity, Citizenship, Customs & Port Security (ICP)",
    },
    "UAE_Cabinet_Resolution_65_2022.pdf": {
        "id": "DOC-006",
        "title": "Cabinet Resolution No. 65 of 2022 Issuing the Executive Regulations of Federal Decree-Law No. 29 of 2021",
        "source_url": "https://uaelegislation.gov.ae/en/legislations/1601",
        "source_type": "regulation",
        "kb_category": "uae_national",
        "domain": "public_services_residency",
        "jurisdiction": "UAE",
        "authority": "UAE Cabinet / ICP",
    },
    "ITU_Y_3172_Architecture.pdf": {
        "id": "DOC-007",
        "title": "ITU-T Recommendation Y.3172: Architectural framework for machine learning in future networks including IMT-2020",
        "source_url": "https://www.itu.int/rec/T-REC-Y.3172-201906-I",
        "source_type": "standard",
        "kb_category": "standard",
        "domain": "telecom_ml_architecture",
        "jurisdiction": "International (ITU)",
        "authority": "ITU-T",
    },
    "AI Ready Framework 2025.pdf": {
        "id": "DOC-008",
        "title": "ITU AI Ready – Analysis Towards a Standardized Readiness Framework (Report 2.0, Jan 2026)",
        "source_url": "https://aiforgood.itu.int/event/ai-for-good-sandbox-hackathon-united-arab-emirates/",
        "source_type": "standard",
        "kb_category": "standard",
        "domain": "ai_readiness_framework",
        "jurisdiction": "International (ITU)",
        "authority": "ITU AI for Good",
    },
}

HEADER_FOOTER_PATTERNS = [
    r"(?m)^Federal Decree by Law Concerning the Protection of Personal Data\s*\d*\s*$",
    r"(?m)^Cabinet Resolution of 2022 Issuing the Executive Regulations.*?Entry and Residence of Foreigners\s*\d*\s*$",
    r"(?m)^Federal Law by Decree No\. \(29\) of 2021 Concerning Entry and Residence of Foreigners\s*\d*\s*$",
    r"(?m)^Rec\.\s*ITU-T\s*Y\.3172.*$",
    r"(?m)^.*AI Ready\s*[–-]\s*Analysis Towards a Standardized Readiness Framework.*$",
    r"(?m)^.*Al Ready\s*[–-]\s*Analysis Towards a Standardized Readiness Framework.*$",
    r"(?m)^\s*Page\s+\d+\s*$",
    r"(?m)^\s*\d+\s*$",
]

ARTICLE_RE = re.compile(r"(?m)^\s*Article\s*\(?(\d+)\)?(\s*BIS)?\s*$", re.IGNORECASE)
ANNEX_MARKER_RE = re.compile(
    r"Annex attached to the Cabinet Resolution|Regulating Golden Residence Permits",
    re.IGNORECASE,
)


def normalize_text(text: str) -> str:
    """Clean headers/footers and normalize whitespace while preserving paragraphs."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for pat in HEADER_FOOTER_PATTERNS:
        text = re.sub(pat, "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[^\S\n]+", " ", text)
    return text.strip()


def extract_units_with_pages(reader: pypdf.PdfReader) -> List[Dict[str, Any]]:
    """Extract legal Articles (with page numbers) or page-level units from a PDF."""
    page_texts: List[Tuple[int, str]] = []
    for p_num, page in enumerate(reader.pages, 1):
        try:
            raw_page = page.extract_text() or ""
        except Exception:
            raw_page = ""
        cleaned = normalize_text(raw_page)
        if cleaned:
            page_texts.append((p_num, cleaned))

    if not page_texts:
        return []

    combined = ""
    char_to_page: List[int] = []
    for p_num, p_text in page_texts:
        block = p_text + "\n\n"
        combined += block
        char_to_page.extend([p_num] * len(block))

    matches = list(ARTICLE_RE.finditer(combined))
    if not matches:
        return [
            {"article_ref": f"Page {p_num}", "page": p_num, "text": p_text}
            for p_num, p_text in page_texts
        ]

    annex_match = ANNEX_MARKER_RE.search(combined)
    annex_start = annex_match.start() if annex_match else None

    units: List[Dict[str, Any]] = []
    if matches[0].start() > 100:
        units.append({
            "article_ref": "Preamble",
            "page": char_to_page[0],
            "text": combined[: matches[0].start()].strip(),
        })

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(combined)
        page_num = char_to_page[start]
        art_num = m.group(1)
        bis = " BIS" if m.group(2) else ""
        prefix = "Golden Residency Annex - " if (annex_start and start >= annex_start) else ""
        units.append({
            "article_ref": f"{prefix}Article ({art_num}){bis}",
            "page": page_num,
            "text": combined[start:end].strip(),
        })

    return units


def chunk_text(
    text: str,
    size: int = CONFIG["chunk_size"],
    overlap: int = CONFIG["chunk_overlap"],
    min_chars: int = CONFIG["min_chunk_chars"],
) -> List[str]:
    """Split text into overlapping word-boundary chunks."""
    text = text.strip()
    if not text:
        return []
    chunks, start, n = [], 0, len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            ws = text.rfind(" ", start + int(size * 0.9), end)
            if ws != -1:
                end = ws
        piece = text[start:end].strip()
        if len(piece) >= min_chars:
            chunks.append(piece)
        if end >= n:
            break
        start = max(end - overlap, start + 1)
    return chunks


def load_document_list(docs_dir: Path = RAW_DIR) -> List[Dict[str, Any]]:
    """Load documents from data/kb_manifest.json or scan data/raw/*.pdf directly."""
    if MANIFEST_PATH.exists():
        manifest = json.load(open(MANIFEST_PATH, encoding="utf-8"))
        return manifest.get("documents", [])

    print(f"[i] {MANIFEST_PATH} not found; scanning {docs_dir} directly...")
    docs_list = []
    for idx, pdf_file in enumerate(sorted(docs_dir.glob("*.pdf")), 1):
        meta = DEFAULT_DOCS_META.get(pdf_file.name, {})
        docs_list.append({
            "id": meta.get("id", f"DOC-{idx:03d}"),
            "filename": pdf_file.name,
            "title": meta.get("title", pdf_file.stem.replace("_", " ")),
            "pdf_path": str(pdf_file),
            "source_url": meta.get("source_url", ""),
            "verified": True,
            "metadata": {
                "source_type": meta.get("source_type", "document"),
                "kb_category": meta.get(
                    "kb_category",
                    "standard" if "ITU" in pdf_file.name or "AI Ready" in pdf_file.name else "uae_national",
                ),
                "domain": meta.get("domain", "general"),
                "jurisdiction": meta.get("jurisdiction", "UAE"),
                "authority": meta.get("authority", "Official"),
            },
        })
    return docs_list


def build_index(docs_dir: Path = RAW_DIR) -> Tuple[faiss.Index, List[Dict[str, Any]]]:
    """Parse PDFs, chunk, embed, and save FAISS index + metadata to kb_store/ and data/index/."""
    docs_list = load_document_list(docs_dir)
    records: List[Dict[str, Any]] = []

    for doc in docs_list:
        pdf_path = doc.get("pdf_path") or str(docs_dir / doc["filename"])
        if not doc.get("verified", True) or not Path(pdf_path).exists():
            print(f"SKIP (missing/unverified PDF): {doc.get('id')} - {doc.get('filename')}")
            continue

        reader = pypdf.PdfReader(pdf_path)
        units = extract_units_with_pages(reader)

        doc_chunk_idx = 0
        for unit in units:
            for c_idx, c_text in enumerate(chunk_text(unit["text"])):
                records.append({
                    "doc_id": doc["id"],
                    "source": doc["filename"],
                    "title": doc["title"],
                    "source_url": doc.get("source_url", ""),
                    "portal_page": doc.get("source_url", ""),
                    "page": unit["page"],
                    "article_ref": unit["article_ref"],
                    "chunk": c_idx,
                    "chunk_id": doc_chunk_idx,
                    "text": c_text,
                    **doc.get("metadata", {}),
                })
                doc_chunk_idx += 1
        print(f"[+] {doc['id']} ({doc['filename']}): {len(units)} units -> {doc_chunk_idx} chunks")

    if not records:
        raise ValueError(f"No chunks extracted. Place valid PDFs in {docs_dir}.")

    print(f"\nLoading embedding model: {CONFIG['embedding_model_name']}")
    model = SentenceTransformer(CONFIG["embedding_model_name"])
    emb = model.encode(
        [r["text"] for r in records],
        normalize_embeddings=True,
        show_progress_bar=True,
        convert_to_numpy=True,
    ).astype("float32")

    index = faiss.IndexFlatIP(emb.shape[1])
    index.add(emb)

    # Save to kb_store/ (local pipeline path)
    faiss.write_index(index, str(KB_STORE_DIR / "faiss.index"))
    with open(KB_STORE_DIR / "records.pkl", "wb") as f:
        pickle.dump(records, f)

    # Save to data/index/ (Colab notebook / collector path)
    faiss.write_index(index, str(INDEX_DIR / "faiss.index"))
    faiss.write_index(index, str(INDEX_DIR / "faiss_unified.index"))
    with open(INDEX_DIR / "metadata.pkl", "wb") as f:
        pickle.dump(records, f)
    with open(INDEX_DIR / "config.json", "w", encoding="utf-8") as f:
        json.dump(CONFIG, f, indent=2)

    uae_count = sum(1 for r in records if r.get("kb_category") == "uae_national")
    std_count = sum(1 for r in records if r.get("kb_category") == "standard")
    print(f"\n✅ Indexed {len(records)} total chunks ({uae_count} UAE National, {std_count} ITU Standards)")
    print(f"   Saved to: {KB_STORE_DIR}/ and {INDEX_DIR}/")
    return index, records


if __name__ == "__main__":
    build_index()