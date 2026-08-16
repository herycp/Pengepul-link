import sqlite3
import time
from datetime import datetime
import concurrent.futures
import sys

# Mengambil fungsi parser yang sudah diupdate dari file crawl
from crawl_9tsu import download_html_page, parse_html_page, DB_FILE, export_to_json

BATCH_SIZE = 2500      
MAX_WORKERS = 25       

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
        'new_title': old_title,
        'new_season': old_season,
        'new_episode': old_episode,
        'status': status,
        'changed': False,
        'failed_parsing': False # Flag proteksi baru
    }
    
    if status == 200 and html_content:
        metadata = parse_html_page(html_content, url)
        new_title = metadata.get('title')
        new_season = metadata.get('season')
        new_episode = metadata.get('episode')
        
        def safe_str(val):
            return str(val) if val is not None else None

        # PROTEKSI FATAL: Hanya proses jika new_title valid (Tidak None/Kosong)
        if new_title:
            if new_title != old_title or new_season != old_season or safe_str(new_episode) != safe_str(old_episode):
                result['new_title'] = new_title
                result['new_season'] = new_season
                result['new_episode'] = new_episode
                result['changed'] = True
        else:
            # Jika mendapat 200 tapi title kosong (Misal diblokir Cloudflare Captcha)
            result['failed_parsing'] = True
    else:
        result['failed_parsing'] = True
            
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
            
            # Log output disesuaikan
            if res['changed']:
                s_log = res['new_season'] if res['new_season'] is not None else "NULL"
                e_log = res['new_episode'] if res['new_episode'] is not None else "NULL"
                print(f"[{i}/{len(rows)}] 🔄 UPDATE: {res['url']} -> [{res['new_title']}] S{s_log}E{e_log}")
            elif res.get('failed_parsing'):
                print(f"[{i}/{len(rows)}] ⚠️ GAGAL PARSING/BLOKIR: {res['url']} (Dilewati)")
            else:
                print(f"[{i}/{len(rows)}] ✅ OK / HTTP {res['status']}")
                
    print("\n💾 Menyimpan hasil ke database SQLite secara massal...")
    update_data = []
    log_data = []
    total_diperbaiki = 0
    
    for res in results:
        # Jika gagal parsing / koneksi, JANGAN masukkan ke log agar dieksekusi ulang di batch berikutnya
        if res.get('failed_parsing'):
            continue
            
        log_data.append((res['db_id'],))
        
        if res['changed']:
            ep_val = str(res['new_episode']) if res['new_episode'] is not None else None
            update_data.append((res['new_title'], res['new_season'], ep_val, res['db_id']))
            total_diperbaiki += 1
            
    if update_data:
        cursor.executemany('UPDATE links SET title = ?, season = ?, episode = ? WHERE id = ?', update_data)
    
    if log_data:
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
