"""
extract_nested_embed.py
Program teroptimasi untuk mengekstrak iframe dari halaman blogspherenews.xyz
yang merupakan embed dari embed (nested embed).
"""

import requests
import cloudscraper
import sqlite3
import json
import re
import os
import shutil
import glob
from datetime import datetime
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# 1. KONFIGURASI
# ============================================================

DB_FILE = "links.db"
JSON_FILE = "links.json"
BACKUP_DIR = "backups"
MAX_BACKUPS = 5
BATCH_SIZE = 500
MAX_WORKERS = 10  # Jumlah thread paralel (sangat optimal di GitHub Actions)
TARGET_DOMAIN = "blogspherenews.xyz"
PROGRESS_FILE = "extract_progress.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "identity",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://blogspherenews.xyz"
}

# Reusable Scraper Instance (Mencegah instansiasi berulang)
SCRAPER = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
)
SCRAPER.headers.update(HEADERS)

# ============================================================
# 2. FUNGSI BACKUP & ROTASI (MAKSIMAL 5 BACKUP)
# ============================================================

def create_backup_dir():
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
        print(f"📁 Direktori backup dibuat: {BACKUP_DIR}")
    gitkeep = os.path.join(BACKUP_DIR, ".gitkeep")
    if not os.path.exists(gitkeep):
        with open(gitkeep, 'w') as f:
            f.write("")

def rotate_backups(prefix, max_keep=MAX_BACKUPS):
    """Menghapus backup lama jika jumlahnya melebihi max_keep (5 file)."""
    pattern = os.path.join(BACKUP_DIR, f"{prefix}*.backup_*")
    files = glob.glob(pattern)
    if len(files) <= max_keep:
        return
    files.sort(key=lambda x: os.path.getmtime(x))
    to_delete = files[:-max_keep]
    for f in to_delete:
        try:
            os.remove(f)
            print(f"🗑️  Backup lama dihapus: {f}")
        except Exception as e:
            print(f"⚠️ Gagal menghapus {f}: {e}")

def backup_file_to_repo(filename, prefix=""):
    create_backup_dir()
    if not os.path.exists(filename):
        print(f"⚠️ File {filename} tidak ditemukan, backup skip")
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = os.path.basename(filename)
    backup_name = f"{prefix}{base_name}.backup_{timestamp}"
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    shutil.copy2(filename, backup_path)
    print(f"📦 Backup dibuat: {backup_path}")
    rotate_backups(prefix, MAX_BACKUPS)
    return backup_path

def backup_database():
    return backup_file_to_repo(DB_FILE, "db_")

def backup_json():
    return backup_file_to_repo(JSON_FILE, "json_")

def backup_all():
    print(f"\n📦 Membuat backup (maksimal {MAX_BACKUPS} backup tersimpan)...")
    db_backup = backup_database()
    json_backup = backup_json()
    print(f"✅ Backup selesai: DB={db_backup}, JSON={json_backup}")
    return db_backup, json_backup

# ============================================================
# 3. FUNGSI PROGRESS
# ============================================================

def load_progress():
    if not os.path.exists(PROGRESS_FILE):
        return {'processed_count': 0, 'updated': 0, 'failed': 0}
    try:
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {'processed_count': 0, 'updated': 0, 'failed': 0}

def save_progress(processed_count, total, updated, failed):
    status = {
        'timestamp': datetime.now().isoformat(),
        'total': total,
        'processed': processed_count,
        'updated': updated,
        'failed': failed,
        'remaining': total - processed_count
    }
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=2)

# ============================================================
# 4. FUNGSI WORKER & PARSING
# ============================================================

def get_iframe_from_page(url):
    try:
        # Timeout diturunkan ke 15 detik agar tidak menggantung di GitHub Actions
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
    """Fungsi pekerja untuk multi-threading."""
    record_id, page_url, embed_url = record
    real_embed = get_iframe_from_page(embed_url)
    return record_id, page_url, embed_url, real_embed

def extract_nested_embeds_from_db():
    if not os.path.exists(DB_FILE):
        print(f"❌ File {DB_FILE} tidak ditemukan!")
        return
    
    # Backup DB & JSON terlebih dahulu sebelum modifikasi
    backup_all()
    
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
    
    print(f"\n🔍 Total record target: {total}")
    print(f"📌 Sudah diproses sebelumnya: {start_index}")
    
    end_index = min(start_index + BATCH_SIZE, total)
    batch_rows = all_rows[start_index:end_index]
    
    print(f"🚀 Memproses batch ini: link {start_index+1} - {end_index} ({len(batch_rows)} link) menggunakan {MAX_WORKERS} threads...")
    
    updated = progress.get('updated', 0)
    failed = progress.get('failed', 0)
    processed_count = start_index
    
    # Eksekusi paralel HTTP requests
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_single_record, row): row for row in batch_rows}
        
        for future in as_completed(futures):
            record_id, page_url, embed_url, real_embed = future.result()
            processed_count += 1
            
            if real_embed:
                print(f"[{processed_count}/{total}] ID: {record_id} ➔ ✅ Real embed: {real_embed}")
                cursor.execute("UPDATE links SET embed_url = ? WHERE id = ?", (real_embed, record_id))
                parsed = urlparse(real_embed)
                if parsed.netloc:
                    cursor.execute("UPDATE links SET embed_platform = ? WHERE id = ?", (parsed.netloc, record_id))
                updated += 1
            else:
                print(f"[{processed_count}/{total}] ID: {record_id} ➔ ⚠️ Tidak ditemukan iframe")
                failed += 1
            
            # Commit & simpan progress tiap 25 record
            if (processed_count - start_index) % 25 == 0:
                conn.commit()
                save_progress(processed_count, total, updated, failed)
    
    conn.commit()
    conn.close()
    
    save_progress(processed_count, total, updated, failed)
    
    print(f"\n{'='*50}")
    print(f"✅ BATCH SELESAI!")
    print(f"   - Diproses batch ini: {end_index - start_index} link")
    print(f"   - Total akumulasi diproses: {processed_count} dari {total}")
    print(f"   - Berhasil diupdate: {updated}")
    print(f"   - Gagal/Tidak ada iframe: {failed}")
    print(f"   - Sisa belum diproses: {total - processed_count} link")
    print(f"{'='*50}")
    
    # Backup & Export Hasil Akhir
    backup_database()
    export_to_json()
    
    if processed_count >= total:
        if os.path.exists(PROGRESS_FILE):
            os.remove(PROGRESS_FILE)
            print("🎉 Semua link selesai diproses! Progress file dihapus.")

def export_to_json():
    if not os.path.exists(DB_FILE):
        return
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT url, title, season, episode, image, description, embed_url, embed_platform, created_at FROM links')
    rows = cursor.fetchall()
    conn.close()
    links = []
    for row in rows:
        links.append({
            'url': row[0],
            'title': row[1],
            'season': row[2],
            'episode': row[3],
            'image': row[4],
            'description': row[5],
            'embed_url': row[6],
            'embed_platform': row[7],
            'created_at': row[8]
        })
    output = {'timestamp': datetime.now().isoformat(), 'total': len(links), 'links': links}
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"📁 JSON diperbarui: {len(links)} link")

def process_single_url(url):
    print(f"🔍 Mengekstrak iframe dari: {url}")
    real_embed = get_iframe_from_page(url)
    if real_embed:
        print(f"✅ Iframe ditemukan: {real_embed}")
    else:
        print("❌ Tidak ditemukan iframe di halaman tersebut")

# ============================================================
# 5. FUNGSI MANAJEMEN
# ============================================================

def list_backups():
    create_backup_dir()
    db_files = glob.glob(os.path.join(BACKUP_DIR, "db_*.backup_*"))
    json_files = glob.glob(os.path.join(BACKUP_DIR, "json_*.backup_*"))
    
    if not db_files and not json_files:
        print("❌ Tidak ada backup ditemukan.")
        return
    
    print("\n📦 Daftar Backup Database:")
    print("-" * 60)
    for f in sorted(db_files, key=os.path.getmtime, reverse=True):
        size = os.path.getsize(f) / 1024
        timestamp = datetime.fromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  {os.path.basename(f)} ({size:.1f} KB) - {timestamp}")
    
    print("\n📦 Daftar Backup JSON:")
    print("-" * 60)
    for f in sorted(json_files, key=os.path.getmtime, reverse=True):
        size = os.path.getsize(f) / 1024
        timestamp = datetime.fromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  {os.path.basename(f)} ({size:.1f} KB) - {timestamp}")

def restore_from_backup(backup_name):
    full_path = os.path.join(BACKUP_DIR, backup_name) if not os.path.exists(backup_name) else backup_name
    if not os.path.exists(full_path):
        print(f"❌ File backup tidak ditemukan: {full_path}")
        return False
    backup_database()
    shutil.copy2(full_path, DB_FILE)
    print(f"✅ Database direstore dari: {full_path}")
    export_to_json()
    return True

def show_progress():
    if not os.path.exists(PROGRESS_FILE):
        print("✅ Tidak ada progress aktif (semua selesai atau belum dimulai)")
        return
    with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
        status = json.load(f)
    print("\n📊 PROGRESS EXTRACT NESTED EMBED")
    print("-" * 60)
    print(f"   Total link target: {status.get('total', 0)}")
    print(f"   Diproses: {status.get('processed', 0)}")
    print(f"   Sisa: {status.get('remaining', 0)}")
    print(f"   Berhasil: {status.get('updated', 0)}")
    print(f"   Gagal: {status.get('failed', 0)}")
    print(f"   Terakhir update: {status.get('timestamp', 'N/A')}")
    print("-" * 60)

def reset_progress():
    if os.path.exists(PROGRESS_FILE):
        os.remove(PROGRESS_FILE)
        print("🔄 Progress direset.")
    else:
        print("ℹ️ Tidak ada file progress.")

# ============================================================
# 6. MAIN CLI ENTRY POINT
# ============================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("=" * 60)
        print("🔧 EXTRACT NESTED EMBED")
        print("=" * 60)
        print("Penggunaan:")
        print("  python extract_nested_embed.py --all")
        print("    - Proses 500 link (lanjut dari progress sebelumnya)")
        print("")
        print("  python extract_nested_embed.py <url>")
        print("    - Ekstrak iframe dari satu URL tertentu")
        print("")
        print("  python extract_nested_embed.py --list-backups")
        print("    - Tampilkan daftar backup yang tersedia")
        print("")
        print("  python extract_nested_embed.py --restore <backup_file>")
        print("    - Restore database dari backup")
        print("")
        print("  python extract_nested_embed.py --progress")
        print("    - Tampilkan progress saat ini")
        print("")
        print("  python extract_nested_embed.py --reset")
        print("    - Reset progress (mulai dari awal)")
        print("=" * 60)
        sys.exit(0)
    
    arg = sys.argv[1]
    
    if arg == '--all':
        print("=" * 60)
        print("📡 EXTRACT NESTED EMBED - MODE BATCH PARALEL")
        print(f"📌 Batch size: {BATCH_SIZE} link | Workers: {MAX_WORKERS} threads")
        print(f"📌 Max backups: {MAX_BACKUPS} file per tipe")
        print("=" * 60)
        extract_nested_embeds_from_db()
    elif arg == '--list-backups':
        list_backups()
    elif arg == '--restore' and len(sys.argv) > 2:
        restore_from_backup(sys.argv[2])
    elif arg == '--progress':
        show_progress()
    elif arg == '--reset':
        reset_progress()
    elif arg == '--help':
        print("Petunjuk penggunaan tersedia di menu utama.")
    else:
        process_single_url(arg)
