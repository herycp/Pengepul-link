import os
import sqlite3
import xml.etree.ElementTree as ET
import json
from datetime import datetime

DB_FILE = "links.db"
JSON_FILE = "links.json"
SITEMAP_DIR = "sitemaps"

def migrate_database():
    print(f"🚀 Memulai migrasi 'lastmod' ke dalam database {DB_FILE}...")
    
    # 1. Buka koneksi ke Database
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # 2. Tambahkan kolom 'lastmod' (Abaikan error jika kolom sudah ada)
    try:
        cursor.execute('ALTER TABLE links ADD COLUMN lastmod TEXT')
        print("✅ Kolom 'lastmod' berhasil ditambahkan ke tabel links.")
    except sqlite3.OperationalError:
        print("⚠️ Kolom 'lastmod' sudah ada di tabel links (lanjut ke proses update).")

    # 3. Kumpulkan data url -> lastmod dari semua sitemap yang ada
    if not os.path.exists(SITEMAP_DIR):
        print(f"❌ Folder {SITEMAP_DIR} tidak ditemukan. Pastikan Anda memiliki sitemap yang sudah diunduh.")
        return

    update_batch = []
    total_sitemap_processed = 0

    ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

    print("\n🔍 Membaca data lastmod dari sitemap lokal...")
    for filename in os.listdir(SITEMAP_DIR):
        if filename.endswith('.xml'):
            filepath = os.path.join(SITEMAP_DIR, filename)
            try:
                tree = ET.parse(filepath)
                root = tree.getroot()
                
                for url_elem in root.findall('.//ns:url', ns):
                    loc_node = url_elem.find('ns:loc', ns)
                    lastmod_node = url_elem.find('ns:lastmod', ns)
                    
                    if loc_node is not None and loc_node.text:
                        url = loc_node.text
                        lastmod = lastmod_node.text if lastmod_node is not None else None
                        
                        if lastmod:
                            # Masukkan ke batch (urutan: lastmod, url)
                            update_batch.append((lastmod, url))
                
                total_sitemap_processed += 1
            except Exception as e:
                print(f"⚠️ Gagal membaca {filename}: {e}")

    print(f"✅ Selesai membaca {total_sitemap_processed} sitemap. Ditemukan {len(update_batch)} URL dengan lastmod.")

    # 4. Eksekusi Update secara massal (Bulk Update)
    if update_batch:
        print("💾 Menyimpan data lastmod ke database...")
        cursor.executemany('''
            UPDATE links SET lastmod = ? WHERE url = ?
        ''', update_batch)
        conn.commit()
        print(f"✅ Berhasil mengupdate {cursor.rowcount} baris data di database.")
    
    # 5. Ekspor ulang ke JSON
    print("\n📦 Mengekspor ulang links.json...")
    cursor.execute('SELECT url, title, season, episode, image, description, embed_url, embed_platform, lastmod, created_at FROM links')
    rows = cursor.fetchall()
    
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
            'lastmod': row[8],
            'created_at': row[9]
        })
    
    output = {
        'timestamp': datetime.now().isoformat(), 
        'total': len(links), 
        'links': links
    }
    
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        
    print(f"✅ Ekspor selesai. File {JSON_FILE} sudah diperbarui dengan data lastmod.")
    conn.close()

if __name__ == "__main__":
    migrate_database()
