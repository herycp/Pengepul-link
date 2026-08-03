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
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup

# ============================================================
# 1. KONFIGURASI
# ============================================================

DB_FILE = "links.db"
JSON_FILE = "links.json"
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
# 2. FUNGSI BANTUAN
# ============================================================

def backup_file(filename):
    """Buat backup file dengan timestamp"""
    if not os.path.exists(filename):
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{filename}.backup_nested_{timestamp}"
    shutil.copy2(filename, backup_name)
    print(f"📦 Backup dibuat: {backup_name}")
    return backup_name

def get_iframe_from_page(url):
    """
    Download halaman dan ekstrak iframe pertama yang ditemukan.
    Return: iframe_url atau None
    """
    try:
        # Gunakan cloudscraper untuk melewati Cloudflare
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
        
        # Cari iframe
        iframe = soup.find('iframe')
        if iframe and iframe.get('src'):
            iframe_src = iframe['src'].strip()
            # Jika src relatif, buat absolute
            if iframe_src.startswith('//'):
                iframe_src = 'https:' + iframe_src
            elif iframe_src.startswith('/'):
                parsed = urlparse(url)
                iframe_src = f"{parsed.scheme}://{parsed.netloc}{iframe_src}"
            return iframe_src
        
        # Cari link ke video (alternatif)
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
    """
    if not os.path.exists(DB_FILE):
        print(f"❌ File {DB_FILE} tidak ditemukan!")
        return
    
    # Backup database
    backup_file(DB_FILE)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Cari record yang embed_url mengandung blogspherenews.xyz
    cursor.execute("SELECT id, url, embed_url FROM links WHERE embed_url LIKE ?", (f'%{TARGET_DOMAIN}%',))
    rows = cursor.fetchall()
    
    if not rows:
        print(f"✅ Tidak ada embed yang mengandung {TARGET_DOMAIN}")
        conn.close()
        return
    
    print(f"🔍 Ditemukan {len(rows)} record dengan embed_url mengandung {TARGET_DOMAIN}")
    
    updated = 0
    for idx, (record_id, page_url, embed_url) in enumerate(rows, 1):
        print(f"\n[{idx}/{len(rows)}] ID: {record_id}")
        print(f"   Page URL: {page_url}")
        print(f"   Embed URL: {embed_url}")
        
        # Ekstrak iframe dari halaman embed_url
        real_embed = get_iframe_from_page(embed_url)
        
        if real_embed:
            print(f"   ✅ Real embed: {real_embed}")
            # Update database
            cursor.execute("UPDATE links SET embed_url = ? WHERE id = ?", (real_embed, record_id))
            # Juga update embed_platform
            parsed = urlparse(real_embed)
            platform = parsed.netloc
            if platform:
                cursor.execute("UPDATE links SET embed_platform = ? WHERE id = ?", (platform, record_id))
            updated += 1
        else:
            print(f"   ⚠️ Tidak ditemukan iframe di halaman tersebut")
    
    conn.commit()
    conn.close()
    
    print(f"\n✅ Selesai! {updated} record diupdate.")
    
    # Re-export JSON
    if updated > 0:
        export_to_json()
        print("📁 JSON diperbarui.")

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
# 3. MAIN
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
        print("  python extract_nested_embed.py --help")
        print("    - Tampilkan bantuan ini")
        print("=" * 60)
        sys.exit(0)
    
    if sys.argv[1] == '--all':
        print("=" * 60)
        print("📡 EXTRACT NESTED EMBED - MODE DATABASE")
        print("=" * 60)
        extract_nested_embeds_from_db()
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
        print("=" * 60)
    else:
        url = sys.argv[1]
        process_single_url(url)
