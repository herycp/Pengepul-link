import sqlite3
import json
import os
import shutil
import glob
from datetime import datetime
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import cloudscraper

# ============================================================
# KONFIGURASI
# ============================================================
DB_FILE = "links.db"
JSON_FILE = "links.json"
BACKUP_DIR = "backups"
MAX_BACKUPS = 5
BATCH_SIZE = 500
MAX_WORKERS = 10  # Jumlah thread paralel (sesuaikan dengan GitHub Actions)
TARGET_DOMAIN = "blogspherenews.xyz"
PROGRESS_FILE = "extract_progress.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://blogspherenews.xyz"
}

# Inisialisasi scraper global (reusable)
SCRAPER = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
)
SCRAPER.headers.update(HEADERS)

# ============================================================
# FUNGSI SCRAPING TEROPTIMASI
# ============================================================
def get_iframe_from_page(url):
    """Mendapatkan iframe dengan timeout lebih kecil & reuse scraper."""
    try:
        # Timeout diturunkan ke 15 detik agar tidak menggantung lama
        response = SCRAPER.get(url, timeout=15)
        
        if response.status_code != 200:
            return None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        iframe = soup.find('iframe')
        if iframe and iframe.get('src'):
            iframe_src = iframe['src'].strip()
            if iframe_src.startswith('//'):
                iframe_src = 'https:' + iframe_src
            elif iframe_src.startswith('/'):
                parsed = urlparse(url)
                iframe_src = f"{parsed.scheme}://{parsed.netloc}{iframe_src}"
            return iframe_src
        
        for a in soup.find_all('a', href=True):
            href = a['href']
            if any(x in href for x in ['dailymotion', 'youtube', 'ok.ru', 'vimeo']):
                return href
        
        return None
    except Exception:
        return None

def process_single_record(record):
    """Worker function untuk multi-threading."""
    record_id, page_url, embed_url = record
    real_embed = get_iframe_from_page(embed_url)
    return record_id, real_embed

# ============================================================
# FUNGSI UTAMA DENGAN MULTI-THREADING
# ============================================================
def extract_nested_embeds_from_db():
    if not os.path.exists(DB_FILE):
        print(f"❌ File {DB_FILE} tidak ditemukan!")
        return
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, url, embed_url FROM links WHERE embed_url LIKE ?", (f'%{TARGET_DOMAIN}%',))
    all_rows = cursor.fetchall()
    
    if not all_rows:
        print(f"✅ Tidak ada embed yang mengandung {TARGET_DOMAIN}")
        conn.close()
        return
    
    total = len(all_rows)
    progress = load_progress()
    start_index = progress.get('processed_count', 0)
    
    if start_index >= total:
        print(f"✅ Semua {total} link sudah diproses sebelumnya.")
        conn.close()
        return
    
    end_index = min(start_index + BATCH_SIZE, total)
    batch_rows = all_rows[start_index:end_index]
    
    print(f"🚀 Memproses batch ({len(batch_rows)} link) menggunakan {MAX_WORKERS} threads...")
    
    updated = progress.get('updated', 0)
    failed = progress.get('failed', 0)
    processed_count = start_index
    
    # Jalankan request HTTP secara paralel
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_single_record, row): row for row in batch_rows}
        
        for future in as_completed(futures):
            record_id, real_embed = future.result()
            processed_count += 1
            
            if real_embed:
                cursor.execute("UPDATE links SET embed_url = ? WHERE id = ?", (real_embed, record_id))
                parsed = urlparse(real_embed)
                if parsed.netloc:
                    cursor.execute("UPDATE links SET embed_platform = ? WHERE id = ?", (parsed.netloc, record_id))
                updated += 1
                print(f"[{processed_count}/{total}] ID {record_id} ➔ ✅ {real_embed}")
            else:
                failed += 1
                print(f"[{processed_count}/{total}] ID {record_id} ➔ ⚠️ No iframe")
            
            # Commit tiap 25 record
            if processed_count % 25 == 0:
                conn.commit()
                save_progress(processed_count, total, updated, failed)
    
    conn.commit()
    conn.close()
    
    save_progress(processed_count, total, updated, failed)
    print(f"\n✅ BATCH SELESAI! (Berhasil: {updated}, Gagal: {failed})")
