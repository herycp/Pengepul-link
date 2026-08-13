import sqlite3
import time
from datetime import datetime

# Import dari script utama Anda
from crawl_9tsu import download_html_page, parse_html_page, DB_FILE, export_to_json

BATCH_SIZE = 1000 # Proses 1000 link per eksekusi

def init_mitigasi_table():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Tabel untuk mencatat ID link yang sudah dicek
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mitigasi_log (
            link_id INTEGER PRIMARY KEY
        )
    ''')
    conn.commit()
    conn.close()

def mitigasi_database():
    init_mitigasi_table()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    print(f"Mencari maksimal {BATCH_SIZE} data yang belum dimitigasi...")
    
    # Hanya ambil data yang ID-nya BELUM ADA di tabel mitigasi_log
    cursor.execute(f'''
        SELECT id, url, title, season, episode 
        FROM links 
        WHERE id NOT IN (SELECT link_id FROM mitigasi_log)
        LIMIT {BATCH_SIZE}
    ''')
    rows = cursor.fetchall()
    
    if not rows:
        print("✅ LUAR BIASA! Semua 24.000+ data sudah selesai dimitigasi!")
        return
        
    total_diperbaiki = 0
    
    for row in rows:
        db_id, url, old_title, old_season, old_episode = row
        
        print(f"[{db_id}] Mitigasi: {url}")
        html_content, status = download_html_page(url)
        
        if status == 200 and html_content:
            metadata = parse_html_page(html_content, url)
            new_season = metadata.get('season')
            new_episode = metadata.get('episode')
            
            if new_season != old_season or new_episode != old_episode:
                print(f"  --> KOREKSI: S{old_season}E{old_episode} menjadi S{new_season}E{new_episode}")
                cursor.execute('''
                    UPDATE links SET season = ?, episode = ? WHERE id = ?
                ''', (new_season, new_episode, db_id))
                total_diperbaiki += 1
            else:
                print("  --> OK (Sudah Benar)")
        else:
            print(f"  --> Gagal fetch ulang: HTTP {status}")
            
        # Catat bahwa ID ini sudah diproses (berhasil atau gagal fetch)
        cursor.execute('INSERT OR IGNORE INTO mitigasi_log (link_id) VALUES (?)', (db_id,))
        
        # Simpan state per baris agar aman dari interupsi
        conn.commit()
        
        time.sleep(1) # Delay anti-Cloudflare block
        
    conn.close()
    
    print(f"\nBatch selesai! Berhasil mengoreksi {total_diperbaiki} baris dari batch ini.")
    
    print("Memperbarui file links.json...")
    export_to_json()

if __name__ == "__main__":
    print("=== PROGRAM MITIGASI DB 9TSU (BATCH MODE) ===")
    mitigasi_database()
