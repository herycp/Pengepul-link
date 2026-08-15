import sqlite3
import json
import os
import time
import concurrent.futures
from crawl_9tsu import download_html_page, DB_FILE
from bs4 import BeautifulSoup

OUTPUT_JSON = 'raw_titles.json'
MAX_WORKERS = 15
BATCH_SIZE = 2500  # Eksekusi 2500 judul per run agar aman di Github Actions

def get_existing_data():
    if os.path.exists(OUTPUT_JSON):
        with open(OUTPUT_JSON, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except:
                return {}
    return {}

def fetch_raw_title(url):
    html_content, status = download_html_page(url)
    if status == 200 and html_content:
        try:
            soup = BeautifulSoup(html_content, 'lxml')
            og_title = soup.find('meta', property='og:title')
            h1 = soup.find('h1')
            
            if og_title and og_title.get('content'):
                return url, og_title['content'].strip()
            elif h1:
                return url, h1.get_text(strip=True)
            elif soup.title:
                return url, soup.title.get_text(strip=True)
        except:
            pass
    return url, None

def main():
    print(f"Membaca database {DB_FILE}...")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT url FROM links")
    all_urls = [row[0] for row in cursor.fetchall()]
    conn.close()
    
    existing_data = get_existing_data()
    print(f"Total link di DB: {len(all_urls)}")
    print(f"Judul yang sudah diekstrak: {len(existing_data)}")
    
    # Filter URL yang belum ada di JSON
    urls_to_process = [url for url in all_urls if url not in existing_data]
    
    # POTONG menjadi ukuran BATCH_SIZE (2500)
    urls_to_process = urls_to_process[:BATCH_SIZE]
    
    print(f"Target batch run kali ini: {len(urls_to_process)} link")
    
    if not urls_to_process:
        print("✅ SEMUA TUNTAS! Tidak ada lagi URL yang perlu diekstrak judul mentahnya.")
        return

    print(f"🚀 Memulai scraping {len(urls_to_process)} raw titles dengan {MAX_WORKERS} workers...")
    start_time = time.time()
    
    count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_raw_title, url): url for url in urls_to_process}
        
        for future in concurrent.futures.as_completed(futures):
            count += 1
            url, title = future.result()
            if title:
                existing_data[url] = title
                print(f"[{count}/{len(urls_to_process)}] ✅ {title}")
            else:
                print(f"[{count}/{len(urls_to_process)}] ❌ Gagal mendapatkan title dari URL ini")

    # Save hasil dari batch ini ke JSON agar siap di-push oleh Github Actions
    print("\n💾 Menyimpan hasil batch ke file JSON...")
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, ensure_ascii=False, indent=2)
        
    elapsed = time.time() - start_time
    print(f"🎉 Batch selesai! Waktu eksekusi: {elapsed/60:.2f} menit. Total raw titles terkumpul: {len(existing_data)}")

if __name__ == '__main__':
    print("=== PROGRAM DUMP RAW TITLES (BATCH MODE) ===")
    main()
