import json
import urllib.request
from pathlib import Path
import pypdf

RAW_DIR = Path("data/raw")
MANIFEST_PATH = Path("data/kb_manifest.json")
RAW_DIR.mkdir(parents=True, exist_ok=True)

DOCS = [
    {
        "id": "DOC-001",
        "filename": "UAE_PDPL_45_2021.pdf",
        "title": "Federal Decree-Law No. 45 of 2021 on the Protection of Personal Data",
        "url": "https://uaelegislation.gov.ae/en/legislations/1972/download",
        "source_url": "https://uaelegislation.gov.ae/en/legislations/1972",
        "metadata": {
            "source_type": "law",
            "kb_category": "uae_national",
            "domain": "data_protection",
            "jurisdiction": "UAE",
            "authority": "UAE Data Office",
            "priority": "Priority 1",
        },
    },
    {
        "id": "DOC-002",
        "filename": "UAE_AI_Charter_2024.pdf",
        "title": "UAE Charter for the Development and Use of Artificial Intelligence (2024)",
        "url": "https://uaelegislation.gov.ae/en/policy/download/the-uae-charter-for-the-development-and-use-of-artificial-intelligence",
        "source_url": "https://uaelegislation.gov.ae/en/policy/details/the-uae-charter-for-the-development-and-use-of-artificial-intelligence",
        "metadata": {
            "source_type": "policy",
            "kb_category": "uae_national",
            "domain": "ai_governance",
            "jurisdiction": "UAE",
            "authority": "UAE Cabinet / AI Office",
            "priority": "Priority 1",
        },
    },
    {
        "id": "DOC-003",
        "filename": "UAE_National_AI_Strategy_2031.pdf",
        "title": "UAE National Strategy for Artificial Intelligence 2031",
        "url": "https://staticcdn.mbzuai.ac.ae/mbzuaiwpprd01/2022/07/UAE-National-Strategy-for-Artificial-Intelligence-2031.pdf",
        "source_url": "https://u.ae/en/about-the-uae/strategies-initiatives-and-awards/strategies-plans-and-visions/government-services-and-digital-transformation/uae-strategy-for-artificial-intelligence",
        "metadata": {
            "source_type": "strategy",
            "kb_category": "uae_national",
            "domain": "ai_governance",
            "jurisdiction": "UAE",
            "authority": "Minister of State for Artificial Intelligence",
            "priority": "Priority 1",
        },
    },
    {
        "id": "DOC-004",
        "filename": "UAE_AI_Ethics_Guidelines.pdf",
        "title": "UAE AI Ethics Principles and Guidelines",
        "url": None,
        "source_url": "https://u.ae/en/about-the-uae/digital-uae/digital-technology/artificial-intelligence/ai-resources",
        "metadata": {
            "source_type": "guideline",
            "kb_category": "uae_national",
            "domain": "ai_ethics",
            "jurisdiction": "UAE",
            "authority": "UAE Council for Artificial Intelligence and Blockchain",
            "priority": "Priority 2",
        },
    },
    {
        "id": "DOC-005",
        "filename": "UAE_Decree_Law_29_2021_Entry_Residence.pdf",
        "title": "Federal Decree-Law No. 29 of 2021 Concerning the Entry and Residence of Foreigners",
        "url": "https://uaelegislation.gov.ae/en/legislations/1528/download",
        "source_url": "https://uaelegislation.gov.ae/en/legislations/1528",
        "metadata": {
            "source_type": "law",
            "kb_category": "uae_national",
            "domain": "public_services_residency",
            "jurisdiction": "UAE",
            "authority": "Federal Authority for Identity, Citizenship, Customs & Port Security (ICP)",
            "priority": "Priority 2",
        },
    },
    {
        "id": "DOC-006",
        "filename": "UAE_Cabinet_Resolution_65_2022.pdf",
        "title": "Cabinet Resolution No. 65 of 2022 Issuing the Executive Regulations of Federal Decree-Law No. 29 of 2021",
        "url": None,
        "source_url": "https://uaelegislation.gov.ae/en/legislations/1601",
        "metadata": {
            "source_type": "regulation",
            "kb_category": "uae_national",
            "domain": "public_services_residency",
            "jurisdiction": "UAE",
            "authority": "UAE Cabinet / ICP",
            "priority": "Optional (Policy-Gap Analysis)",
        },
    },
    {
        "id": "DOC-007",
        "filename": "ITU_Y_3172_Architecture.pdf",
        "title": "ITU-T Recommendation Y.3172: Architectural framework for machine learning in future networks including IMT-2020",
        "url": "https://www.itu.int/rec/dologin_pub.asp?lang=e&id=T-REC-Y.3172-201906-I!!PDF-E&type=items",
        "source_url": "https://www.itu.int/rec/T-REC-Y.3172-201906-I",
        "metadata": {
            "source_type": "standard",
            "kb_category": "standard",
            "domain": "telecom_ml_architecture",
            "jurisdiction": "International (ITU)",
            "authority": "ITU-T",
            "priority": "ITU Standard",
        },
    },
    {
        "id": "DOC-008",
        "filename": "AI Ready Framework 2025.pdf",
        "title": "ITU AI Ready – Analysis Towards a Standardized Readiness Framework (Report 2.0, Jan 2026)",
        "url": "https://www.itu.int/dms_pub/itu-t/opb/ai4g/T-AI4G-AI4GOOD-2025-6-PDF-E.pdf",
        "source_url": "https://aiforgood.itu.int/event/ai-for-good-sandbox-hackathon-united-arab-emirates/",
        "metadata": {
            "source_type": "standard",
            "kb_category": "standard",
            "domain": "ai_readiness_framework",
            "jurisdiction": "International (ITU)",
            "authority": "ITU AI for Good",
            "priority": "ITU Standard",
        },
    },
]


def is_valid_pdf(path: Path) -> bool:
    if not (path.exists() and path.stat().st_size > 5000 and path.read_bytes()[:4] == b"%PDF"):
        return False
    try:
        reader = pypdf.PdfReader(str(path))
        return len(reader.pages) > 0
    except Exception:
        return False


def download_and_verify_docs() -> None:
    print("=" * 75)
    print("Checking & Verifying Official PDF Documents")
    print("=" * 75)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    manifest_docs = []

    for doc in DOCS:
        path = RAW_DIR / doc["filename"]
        url = doc.get("url")

        if not is_valid_pdf(path) and url:
            try:
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=30) as r:
                    content = r.read()
                if content[:4] == b"%PDF":
                    path.write_bytes(content)
                    print(f"[+] Downloaded {doc['filename']}")
            except Exception as e:
                print(f"[!] Auto-download failed for {doc['filename']} ({type(e).__name__}).")

        valid = is_valid_pdf(path)
        if valid:
            print(f"[OK] {doc['id']} | {doc['filename']} ({path.stat().st_size // 1024} KB)")
        else:
            print(f"[MISSING/CORRUPT] {doc['id']} | {doc['filename']} -> place valid PDF in {RAW_DIR}")

        manifest_docs.append({
            "id": doc["id"],
            "filename": doc["filename"],
            "title": doc["title"],
            "pdf_path": str(path).replace("\\", "/") if valid else None,
            "source_url": doc["source_url"],
            "verified": valid,
            "metadata": doc["metadata"],
        })

    manifest = {
        "project": "UAE Government AI Bias & Policy Auditing",
        "standard_compliance": ["ITU-T Y.3172", "ITU AI Readiness Framework 2.0"],
        "documents": manifest_docs,
    }
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"\n[+] Saved manifest to {MANIFEST_PATH}")


if __name__ == "__main__":
    download_and_verify_docs()