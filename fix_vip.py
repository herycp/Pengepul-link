import sys
import sqlite3
import time
from crawl_9tsu import download_html_page, parse_html_page, DB_FILE, export_to_json

def fix_data_from_vip(target_ids):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # 1. Parsing input ID (mendukung format "12, 34, 56")
    try:
        ids = [int(i.strip()) for i in target_ids.split(",") if i.strip().isdigit()]
    except ValueError:
        print("❌ Format ID tidak valid.")
        return

    if not ids:
        print("⚠️ Tidak ada ID valid yang diberikan.")
        return

    # 2. Ambil data asli dari database
    placeholders = ','.join(['?'] * len(ids))
    cursor.execute(f"SELECT id, url, title FROM links WHERE id IN ({placeholders})", ids)
    rows = cursor.fetchall()
    
    if not rows:
        print("⚠️ Tidak ada data ditemukan untuk kumpulan ID tersebut.")
        return

    print(f"🚀 Memproses {len(rows)} data perbaikan dari 9tsu.vip...")
    
    update_data = []
    
    for db_id, original_url, old_title in rows:
        # 3. Konversi URL ke format VIP
        # Mengubah https://9tsu.in/douga/123.html -> https://9tsu.vip/123.html
        vip_url = original_url.replace("9tsu.in/douga/", "9tsu.vip/")
        vip_url = vip_url.replace("9tsu.in/duga/", "9tsu.vip/") # Jaga-jaga jika ada typo 'duga'
        
        print(f"\n🔄 Mengunduh HTML dari VIP: {vip_url}")
        html_content, status = download_html_page(vip_url)
        
        if status == 200 and html_content:
            # Tetap oper original_url agar link di database tidak berubah domainnya, hanya metadatanya saja yang diupdate
            metadata = parse_html_page(html_content, original_url) 
            new_title = metadata.get('title')
            
            if new_title:
                s_log = metadata.get('season') if metadata.get('season') is not None else "NULL"
                e_log = metadata.get('episode') if metadata.get('episode') is not None else "NULL"
                
                print(f"✅ SUKSES: [{old_title}] -> [{new_title}] S{s_log}E{e_log}")
                
                # Menyiapkan data untuk di-update
                ep_val = str(metadata.get('episode')) if metadata.get('episode') is not None else None
                update_data.append((
                    new_title, 
                    metadata.get('season'), 
                    ep_val,
                    metadata.get('image'),
                    metadata.get('description'),
                    metadata.get('embed_url'),
                    metadata.get('embed_platform'),
                    db_id
                ))
            else:
                print(f"⚠️ GAGAL PARSING: Halaman kosong atau diblokir dari VIP.")
        else:
            print(f"❌ GAGAL DOWNLOAD: HTTP {status} dari VIP.")
        
        time.sleep(1.5) # Jeda sopan antar request agar tidak diblokir VIP
        
    # 4. Simpan ke database
    if update_data:
        print("\n💾 Menyimpan pembaruan ke database...")
        cursor.executemany('''
            UPDATE links 
            SET title = ?, season = ?, episode = ?, image = ?, description = ?, embed_url = ?, embed_platform = ?
            WHERE id = ?
        ''', update_data)
        conn.commit()
        print(f"✅ {len(update_data)} baris berhasil diperbarui.")
        export_to_json()
    else:
        print("\n⚠️ Tidak ada data yang berhasil diperbarui.")
        
    conn.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        input_ids = sys.argv[1]
        fix_data_from_vip(input_ids)
    else:
        print("❌ Harap berikan ID database. Contoh: python fix_vip.py 12,34,56")
