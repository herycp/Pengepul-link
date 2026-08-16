import sqlite3
import time
from datetime import datetime
import concurrent.futures
import sys

# Mengambil fungsi parser yang sudah diupdate dari file crawl
from crawl_9tsu import download_html_page, parse_html_page, DB_FILE, export_to_json

BATCH_SIZE = 1000      
MAX_WORKERS = 15       

def init_mitigasi_table():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mitigasi_log (
            link_id INTEGER PRIMARY KEY
        )
    ''')
    conn.commit()
    conn.close()

def process_url(row):
    db_id, url, old_title, old_season, old_episode = row
    html_content, status = download_html_page(url)
    
    result = {
        'db_id': db_id,
        'url': url,
        'new_season': old_season,
        'new_episode': old_episode,
        'status': status,
        'changed': False
    }
    
    if status == 200 and html_content:
        metadata = parse_html_page(html_content, url)
        new_season = metadata.get('season')
        new_episode = metadata.get('episode')
        
        # Bandingkan sebagai string untuk mencegah bypass error tipe (misal: "1,2" vs 1)
        if new_season != old_season or str(new_episode) != str(old_episode):
            result['new_season'] = new_season
            result['new_episode'] = new_episode
            result['changed'] = True
            
    return result

def mitigasi_database():
    if '--reset' in sys.argv:
        print("🔄 Opsi --reset terdeteksi. Menghapus rekaman mitigasi_log...")
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('DROP TABLE IF EXISTS mitigasi_log')
        conn.commit()
        conn.close()
        print("✅ Log berhasil dibersihkan. Semua data akan dimitigasi ulang.")

    init_mitigasi_table()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    print(f"Mencari maksimal {BATCH_SIZE} data yang belum dimitigasi...")
    
    cursor.execute(f'''
        SELECT id, url, title, season, episode 
        FROM links 
        WHERE id NOT IN (SELECT link_id FROM mitigasi_log)
        LIMIT {BATCH_SIZE}
    ''')
    rows = cursor.fetchall()
    
    if not rows:
        print("✅ LUAR BIASA! Semua data sudah selesai dimitigasi!")
        conn.close()
        return
        
    print(f"🚀 Memulai pemrosesan Multi-Threading dengan {MAX_WORKERS} pekerja...")
    start_time = time.time()
    results = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_url, row) for row in rows]
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            res = future.result()
            results.append(res)
            if res['changed']:
                print(f"[{i}/{len(rows)}] 🔄 KOREKSI: {res['url']} -> S{res['new_season']}E{res['new_episode']}")
            else:
                print(f"[{i}/{len(rows)}] ✅ OK / HTTP {res['status']}")
                
    print("\n💾 Menyimpan hasil ke database SQLite secara massal...")
    update_data = []
    log_data = []
    total_diperbaiki = 0
    
    for res in results:
        log_data.append((res['db_id'],))
        if res['changed']:
            # Menyimpan episode sebagai string secara paksa
            update_data.append((res['new_season'], str(res['new_episode']), res['db_id']))
            total_diperbaiki += 1
            
    if update_data:
        cursor.executemany('UPDATE links SET season = ?, episode = ? WHERE id = ?', update_data)
    
    cursor.executemany('INSERT OR IGNORE INTO mitigasi_log (link_id) VALUES (?)', log_data)
    conn.commit()
    conn.close()
    
    elapsed = time.time() - start_time
    print(f"\n⏱️ Selesai! Waktu eksekusi: {elapsed:.2f} detik ({elapsed/60:.2f} menit).")
    print(f"Berhasil mengoreksi {total_diperbaiki} baris dari batch ini.")
    
    print("Memperbarui file links.json...")
    export_to_json()

if __name__ == "__main__":
    print("=== PROGRAM MITIGASI DB 9TSU (MULTI-THREADING MODE) ===")
    mitigasi_database()
