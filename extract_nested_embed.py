"""
extract_nested_embed.py
Program untuk mengekstrak iframe dari halaman blogspherenews.xyz
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
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup

# ============================================================
# 1. KONFIGURASI
# ============================================================

DB_FILE = "links.db"
JSON_FILE = "links.json"
BACKUP_DIR = "backups"
MAX_BACKUPS = 5  # 🔥 Maksimal 5 backup
BATCH_SIZE = 100
TARGET_DOMAIN = "blogspherenews.xyz"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "identity",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://blogspherenews.xyz"
}

# ============================================================
# 2. FUNGSI BACKUP & ROTASI
# ============================================================

def create_backup_dir():
    """Buat direktori backup jika belum ada"""
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
        print(f"📁 Direktori backup dibuat: {BACKUP_DIR}")

def rotate_backups(prefix, max_keep=MAX_BACKUPS):
    """
    Rotasi backup: hapus backup lama, hanya pertahankan max_keep terbaru.
    prefix: 'db_' atau 'json_'
    """
    pattern = os.path.join(BACKUP_DIR, f"{prefix}*.backup_*")
    files = glob.glob(pattern)
    
    if len(files) <= max_keep:
        return
    
    # Urutkan berdasarkan waktu (yang paling tua dihapus)
    files.sort(key=lambda x: os.path.getmtime(x))
    to_delete = files[:-max_keep]
    
    for f in to_delete:
        os.remove(f)
        print(f"🗑️  Backup lama dihapus: {f}")

def backup_file_to_repo(filename, prefix=""):
    """
    Backup file ke folder backups/ dengan timestamp.
    Return: path backup
    """
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
    
    # 🔥 Rotasi backup setelah membuat baru
    rotate_backups(prefix, MAX_BACKUPS)
    
    return backup_path

def backup_database():
    """Backup database ke folder backups/"""
    return backup_file_to_repo(DB_FILE, "db_")

def backup_json():
    """Backup JSON ke folder backups/"""
    return backup_file_to_repo(JSON_FILE, "json_")

def backup_all():
    """Backup semua file penting"""
    print(f"\n📦 Membuat backup (max {MAX_BACKUPS} per type)...")
    db_backup = backup_database()
    json_backup = backup_json()
    print(f"✅ Backup selesai: DB={db_backup}, JSON={json_backup}")
    return db_backup, json_backup

# ============================================================
# 3. FUNGSI UTAMA
# ============================================================

def get_iframe_from_page(url):
    """
    Download halaman dan ekstrak iframe pertama yang ditemukan.
    Return: iframe_url atau None
    """
    try:
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
            delay=True,
            interpreter='native'
        )
        scraper.headers.update(HEADERS)
        response = scraper.get(url, timeout=60)
        
        if response.status_code != 200:
            print(f"   ❌ Gagal download {url} (status {response.status_code})")
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
    except Exception as e:
        print(f"   ❌ Error processing {url}: {e}")
        return None

def extract_nested_embeds_from_db():
    """
    Cari semua link di database yang embed_url-nya mengandung blogspherenews.xyz.
    Ekstrak iframe sebenarnya dan update database.
    Batch size: 100 link per run.
    """
    if not os.path.exists(DB_FILE):
        print(f"❌ File {DB_FILE} tidak ditemukan!")
        return
    
    # 🔥 Backup sebelum perubahan
    backup_all()
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Cari record yang embed_url mengandung blogspherenews.xyz
    cursor.execute("SELECT id, url, embed_url FROM links WHERE embed_url LIKE ?", (f'%{TARGET_DOMAIN}%',))
    rows = cursor.fetchall()
    
    if not rows:
        print(f"✅ Tidak ada embed yang mengandung {TARGET_DOMAIN}")
        conn.close()
        return
    
    total = len(rows)
    print(f"🔍 Ditemukan {total} record dengan embed_url mengandung {TARGET_DOMAIN}")
    print(f"📌 Batch size: {BATCH_SIZE} link per run")
    
    updated = 0
    failed = 0
    
    # 🔥 Proses dalam batch
    for batch_start in range(0, total, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, total)
        batch_rows = rows[batch_start:batch_end]
        
        print(f"\n{'='*50}")
        print(f"📌 BATCH {batch_start//BATCH_SIZE + 1}: link {batch_start+1} - {batch_end} dari {total}")
        print(f"{'='*50}")
        
        for idx, (record_id, page_url, embed_url) in enumerate(batch_rows, batch_start + 1):
            print(f"\n[{idx}/{total}] ID: {record_id}")
            print(f"   Page URL: {page_url}")
            print(f"   Embed URL: {embed_url}")
            
            real_embed = get_iframe_from_page(embed_url)
            
            if real_embed:
                print(f"   ✅ Real embed: {real_embed}")
                cursor.execute("UPDATE links SET embed_url = ? WHERE id = ?", (real_embed, record_id))
                parsed = urlparse(real_embed)
                platform = parsed.netloc
                if platform:
                    cursor.execute("UPDATE links SET embed_platform = ? WHERE id = ?", (platform, record_id))
                updated += 1
            else:
                print(f"   ⚠️ Tidak ditemukan iframe di halaman tersebut")
                failed += 1
        
        # 🔥 Commit setiap batch
        conn.commit()
        
        # 🔥 Backup setelah setiap batch (incremental backup)
        print(f"\n📦 Backup setelah batch...")
        backup_database()
        export_to_json()
        print(f"📁 JSON diperbarui setelah batch")
        
        # 🔥 Update progress di file status
        update_progress_file(batch_start + len(batch_rows), total, updated, failed)
    
    conn.close()
    
    print(f"\n{'='*50}")
    print(f"✅ SELESAI!")
    print(f"   - Total diproses: {total}")
    print(f"   - Berhasil diupdate: {updated}")
    print(f"   - Gagal: {failed}")
    print(f"{'='*50}")
    
    # Final backup
    backup_all()
    export_to_json()
    print("📁 JSON final diperbarui.")

def update_progress_file(processed, total, updated, failed):
    """Update file status progress"""
    status = {
        'timestamp': datetime.now().isoformat(),
        'total': total,
        'processed': processed,
        'updated': updated,
        'failed': failed,
        'remaining': total - processed
    }
    with open('extract_progress.json', 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=2)

def export_to_json():
    """Ekspor ulang database ke JSON"""
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
    print(f"📁 JSON ekspor: {len(links)} link")

def process_single_url(url):
    """Proses satu URL dan tampilkan iframe yang ditemukan"""
    print(f"🔍 Mengekstrak iframe dari: {url}")
    real_embed = get_iframe_from_page(url)
    if real_embed:
        print(f"✅ Iframe ditemukan: {real_embed}")
    else:
        print("❌ Tidak ditemukan iframe di halaman tersebut")

# ============================================================
# 4. FUNGSI MANAJEMEN BACKUP
# ============================================================

def list_backups():
    """Tampilkan daftar backup yang tersedia"""
    create_backup_dir()
    
    db_files = glob.glob(os.path.join(BACKUP_DIR, "db_*.backup_*"))
    json_files = glob.glob(os.path.join(BACKUP_DIR, "json_*.backup_*"))
    
    if not db_files and not json_files:
        print("❌ Tidak ada backup ditemukan.")
        return
    
    print("\n📦 Daftar Backup (Database):")
    print("-" * 60)
    for f in sorted(db_files, key=os.path.getmtime, reverse=True):
        size = os.path.getsize(f) / 1024
        timestamp = datetime.fromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  {os.path.basename(f)} ({size:.1f} KB) - {timestamp}")
    
    print("\n📦 Daftar Backup (JSON):")
    print("-" * 60)
    for f in sorted(json_files, key=os.path.getmtime, reverse=True):
        size = os.path.getsize(f) / 1024
        timestamp = datetime.fromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  {os.path.basename(f)} ({size:.1f} KB) - {timestamp}")

def restore_from_backup(backup_name):
    """Restore database dari backup"""
    full_path = os.path.join(BACKUP_DIR, backup_name) if not os.path.exists(backup_name) else backup_name
    
    if not os.path.exists(full_path):
        print(f"❌ File backup tidak ditemukan: {full_path}")
        return False
    
    # Backup current database dulu
    backup_database()
    
    # Restore
    shutil.copy2(full_path, DB_FILE)
    print(f"✅ Database direstore dari: {full_path}")
    export_to_json()
    return True

def cleanup_old_backups():
    """Bersihkan semua backup lama (manual cleanup)"""
    create_backup_dir()
    
    # Hapus semua backup
    for f in glob.glob(os.path.join(BACKUP_DIR, "*.backup_*")):
        os.remove(f)
        print(f"🗑️  Dihapus: {f}")
    
    print("✅ Semua backup dibersihkan.")

# ============================================================
# 5. MAIN
# ============================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("=" * 60)
        print("🔧 EXTRACT NESTED EMBED")
        print("=" * 60)
        print("Penggunaan:")
        print("  python extract_nested_embed.py --all")
        print("    - Proses semua embed di database yang mengandung blogspherenews.xyz")
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
        print("  python extract_nested_embed.py --cleanup")
        print("    - Hapus semua backup (hati-hati!)")
        print("=" * 60)
        sys.exit(0)
    
    if sys.argv[1] == '--all':
        print("=" * 60)
        print("📡 EXTRACT NESTED EMBED - MODE DATABASE")
        print(f"📌 Batch size: {BATCH_SIZE} link per cycle")
        print(f"📌 Max backups: {MAX_BACKUPS} per type")
        print("=" * 60)
        extract_nested_embeds_from_db()
    elif sys.argv[1] == '--list-backups':
        list_backups()
    elif sys.argv[1] == '--restore' and len(sys.argv) > 2:
        restore_from_backup(sys.argv[2])
    elif sys.argv[1] == '--cleanup':
        print("⚠️  Yakin ingin menghapus semua backup? (y/n)")
        confirm = input()
        if confirm.lower() == 'y':
            cleanup_old_backups()
        else:
            print("❌ Dibatalkan.")
    elif sys.argv[1] == '--help':
        print("=" * 60)
        print("🔧 EXTRACT NESTED EMBED - HELP")
        print("=" * 60)
        print("Penggunaan:")
        print("  python extract_nested_embed.py --all")
        print("    - Proses semua embed di database yang mengandung blogspherenews.xyz")
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
        print("  python extract_nested_embed.py --cleanup")
        print("    - Hapus semua backup (hati-hati!)")
        print("=" * 60)
    else:
        url = sys.argv[1]
        process_single_url(url)
