import httpx
from pathlib import Path

RAW_DIR = Path("data/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)

PDF_SOURCES = {
    "UAE_PDPL_45_2021.pdf": "https://uaelegislation.gov.ae/en/legislations/1972/download",
    "UAE_Residency_29_2021.pdf": "https://uaelegislation.gov.ae/en/legislations/1527/download",
    "UAE_Cabinet_Res_65_2022.pdf": "https://uaelegislation.gov.ae/ar/legislations/1605/download",
    "UAE_AI_Charter_2024.pdf": "https://ai.gov.ae/wp-content/uploads/2024/07/UAE-AI-Charter.pdf",
    "EU_AI_Act_2024.pdf": "https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=OJ:L_202401689",
    "UNESCO_AI_Ethics_2021.pdf": "https://unesdoc.unesco.org/ark:/48223/pf0000381137.pdf",
    "OECD_AI_Principles_2024.pdf": "https://oecd.ai/en/wonk/documents/oecd-ai-principles.pdf",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

def download_all():
   
    with httpx.Client(verify=False, headers=HEADERS, timeout=60.0, follow_redirects=True) as client:
        for filename, url in PDF_SOURCES.items():
            dest = RAW_DIR / filename
            if dest.exists() and dest.stat().st_size > 1000:
                print(f"[EXISTS] {filename}")
                continue
                
            print(f"[DOWNLOADING] {filename}...")
            try:
                resp = client.get(url)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
                print(f"[OK] Saved to {dest}")
            except Exception as e:
                print(f"[WARN] Failed {filename}: {e}")

if __name__ == "__main__":
    download_all()