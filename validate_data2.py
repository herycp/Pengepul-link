"""
validate_data2.py (Optimized & Resilient Version)
Validasi data dengan pendekatan:
1. Query untuk mencari semua data mencurigakan (duplikat, domain lain, NULL kecuali season & episode)
2. Filter URL unik agar setiap URL hanya di-scrape 1x meskipun dimiliki banyak record
3. Verifikasi dengan Multithreading (Auto-retry antrian belakang jika HTTP Error/Timeout max 3x)
4. Laporan detail hasil verifikasi (reports/05_data_validation_report.md)
"""

import sqlite3
import os
import cloudscraper
import re
import concurrent.futures
from datetime import datetime
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

DB_FILE = "links.db"
REPORTS_DIR = "reports"
OUTPUT_FILE = "05_data_validation_report.md"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "identity",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}

# Tentukan jumlah maksimal request bersamaan
MAX_WORKERS = 10 
# Tentukan batas maksimal percobaan (retry)
MAX_RETRIES = 3

def ensure_reports_dir():
    if not os.path.exists(REPORTS_DIR):
        os.makedirs(REPORTS_DIR)

def transform_url(url):
    """Transformasi URL dari 9tsu.in/douga/* ke 9tsu.vip/*"""
    url = url.replace('9tsu.in', '9tsu.vip')
    url = re.sub(r'/douga/', '/', url)
    return url

def get_all_suspicious_records():
    """Ambil SEMUA record yang termasuk dalam 3 kategori mencurigakan."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    suspicious = {}
    
    # 1. Duplikat embed_url
    cursor.execute("""
        SELECT id, url, embed_url, embed_platform
        FROM links
        WHERE embed_url IN (
            SELECT embed_url FROM links
            WHERE embed_url IS NOT NULL AND embed_url != ''
            GROUP BY embed_url
            HAVING COUNT(*) > 1
        )
        AND embed_url IS NOT NULL AND embed_url != ''
    """)
    for row in cursor.fetchall():
        id_, url, embed, platform = row
        if id_ not in suspicious:
            suspicious[id_] = {'id': id_, 'url': url, 'embed_url': embed, 'embed_platform': platform, 'issues': []}
        suspicious[id_]['issues'].append('duplicate')
    
    # 2. Domain di luar ok.ru dan brinqeo.guru
    cursor.execute("""
        SELECT id, url, embed_url, embed_platform
        FROM links
        WHERE embed_url IS NOT NULL AND embed_url != ''
        AND embed_url NOT LIKE '%ok.ru%'
        AND embed_url NOT LIKE '%brinqeo.guru%'
    """)
    for row in cursor.fetchall():
        id_, url, embed, platform = row
        if id_ not in suspicious:
            suspicious[id_] = {'id': id_, 'url': url, 'embed_url': embed, 'embed_platform': platform, 'issues': []}
        suspicious[id_]['issues'].append('other_domain')
    
    # 3. NULL values (Pengecualian: season & episode dihapus dari daftar)
    fields = ['url', 'title', 'image', 'description', 'embed_url', 'embed_platform']
    for field in fields:
        cursor.execute(f"""
            SELECT id, url, embed_url, embed_platform
            FROM links
            WHERE {field} IS NULL OR {field} = ''
        """)
        for row in cursor.fetchall():
            id_, url, embed, platform = row
            if id_ not in suspicious:
                suspicious[id_] = {'id': id_, 'url': url, 'embed_url': embed, 'embed_platform': platform, 'issues': []}
            suspicious[id_]['issues'].append(f'null_{field}')
    
    conn.close()
    
    result = list(suspicious.values())
    print(f"🔍 Total record mencurigakan: {len(result)}")
    return result

def scrape_embed_vip(url, scraper):
    """Scrape halaman di 9tsu.vip menggunakan sesi scraper."""
    vip_url = transform_url(url)
    try:
        response = scraper.get(vip_url, timeout=15)
        if response.status_code != 200:
            return None, f"HTTP {response.status_code} (URL: {vip_url})"
        
        soup = BeautifulSoup(response.text, 'html.parser')
        iframe = soup.find('iframe')
        
        if iframe and iframe.get('src'):
            embed_url = iframe['src'].strip()
            if embed_url.startswith('//'):
                embed_url = 'https:' + embed_url
            return embed_url, None
            
        for a in soup.find_all('a', href=True):
            href = a['href']
            if any(x in href for x in ['dailymotion', 'youtube', 'ok.ru', 'vimeo', 'pulvexa']):
                return href, None
                
        return None, "Tidak ditemukan embed"
    except Exception as e:
        return None, str(e)

def generate_report():
    """Generate laporan Markdown"""
    ensure_reports_dir()
    
    if not os.path.exists(DB_FILE):
        filepath = os.path.join(REPORTS_DIR, OUTPUT_FILE)
        with open(filepath, "w") as f:
            f.write("# ❌ Error\nlinks.db tidak ditemukan")
        return
    
    print("=" * 60)
    print("📡 VALIDASI DATA (9tsu.vip) - Mencari data mencurigakan...")
    print("=" * 60)
    
    suspicious_records = get_all_suspicious_records()
    
    if not suspicious_records:
        print("✅ Tidak ada data mencurigakan!")
        filepath = os.path.join(REPORTS_DIR, OUTPUT_FILE)
        with open(filepath, "w") as f:
            f.write("# ✅ Laporan Validasi Data (9tsu.vip)\n\n**Tidak ada data mencurigakan ditemukan.**")
        return
    
    # --- FITUR 1: DEDUPLIKASI URL ---
    unique_urls = list(set([rec['url'] for rec in suspicious_records]))
    print(f"🎯 Memfilter menjadi {len(unique_urls)} URL Unik yang akan di-scrape.")
    print(f"🚀 Memulai proses dengan {MAX_WORKERS} Threads (Maks {MAX_RETRIES}x retry untuk error)...")
    print("-" * 60)

    global_scraper = cloudscraper.create_scraper(
        browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
        interpreter='native'
    )
    global_scraper.headers.update(HEADERS)
    
    url_results = {}
    
    # --- FITUR 2: ANTRIAN DAN RETRY ---
    tasks = [{'url': url, 'try_count': 1} for url in unique_urls]
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(scrape_embed_vip, task['url'], global_scraper): task for task in tasks}
        
        while futures:
            done, _ = concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
            
            for future in done:
                task = futures.pop(future)
                url = task['url']
                try_count = task['try_count']
                
                try:
                    real_embed, error = future.result()
                except Exception as e:
                    real_embed, error = None, str(e)
                
                is_network_or_http_error = error and error != "Tidak ditemukan embed"
                
                if is_network_or_http_error and try_count < MAX_RETRIES:
                    print(f"   ⚠️ [Attempt {try_count}/{MAX_RETRIES}] Gagal: {url} ({error}) -> Dipindah ke akhir antrian...")
                    task['try_count'] += 1
                    new_future = executor.submit(scrape_embed_vip, task['url'], global_scraper)
                    futures[new_future] = task
                else:
                    url_results[url] = {'real_embed': real_embed, 'error': error}
                    status_msg = f"✅ Sukses" if real_embed else f"❌ Gagal ({error})"
                    print(f"   [{len(url_results)}/{len(unique_urls)}] Selesai: {url} | {status_msg}")

    results = []
    for rec in suspicious_records:
        url = rec['url']
        res_data = url_results[url]
        real_embed = res_data['real_embed']
        error = res_data['error']
        
        status = 'verified' if real_embed == rec['embed_url'] else ('mismatch' if real_embed else 'error')
        
        results.append({
            'id': rec['id'],
            'url': rec['url'],
            'vip_url': transform_url(rec['url']),
            'db_embed': rec['embed_url'],
            'db_platform': rec['embed_platform'],
            'issues': rec['issues'],
            'real_embed': real_embed,
            'error': error,
            'status': status
        })
    
    total = len(results)
    verified = sum(1 for r in results if r['status'] == 'verified')
    mismatch = sum(1 for r in results if r['status'] == 'mismatch')
    error_count = sum(1 for r in results if r['status'] == 'error')
    
    issue_counts = {}
    for r in results:
        for issue in r['issues']:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    md = []
    md.append("# 📋 Laporan Validasi Data (9tsu.vip)\n")
    md.append(f"_Diperbarui: `{now}`_\n")
    md.append(f"**Domain yang diverifikasi:** `https://9tsu.vip`\n")
    md.append(f"**Total record mencurigakan:** `{total}` (Terdiri dari `{len(unique_urls)}` URL Unik)\n")
    
    md.append("## 📊 Ringkasan Kategori\n")
    md.append("| Kategori | Jumlah Record |")
    md.append("| :--- | :---: |")
    for issue, count in sorted(issue_counts.items()):
        md.append(f"| `{issue}` | `{count}` |")
    md.append("")
    
    md.append("## 🎯 Hasil Verifikasi Scraping (9tsu.vip)\n")
    md.append("| Status | Jumlah | Persentase |")
    md.append("| :--- | :---: | :---: |")
    md.append(f"| ✅ Cocok | `{verified}` | `{verified/total*100:.1f}%` |")
    md.append(f"| ❌ Tidak Cocok | `{mismatch}` | `{mismatch/total*100:.1f}%` |")
    md.append(f"| ⚠️ Error Scraping | `{error_count}` | `{error_count/total*100:.1f}%` |")
    md.append("")
    
    duplicate_groups = {}
    for r in results:
        if 'duplicate' in r['issues']:
            key = r['db_embed']
            if key not in duplicate_groups:
                duplicate_groups[key] = []
            duplicate_groups[key].append(r)
    
    if duplicate_groups:
        md.append("## 1. Detail Duplikat (Kelompok)\n")
        for embed_url, group in duplicate_groups.items():
            md.append(f"### `{embed_url}` ({len(group)} record)\n")
            md.append("| ID | URL Asli (9tsu.in) | URL 9tsu.vip | Status | Real Embed |")
            md.append("| :---: | :--- | :--- | :---: | :--- |")
            for r in group:
                status_icon = "✅" if r['status'] == 'verified' else ("❌" if r['status'] == 'mismatch' else "⚠️")
                real_display = r['real_embed'] if r['real_embed'] else f"Error: {r['error']}"
                md.append(f"| {r['id']} | `{r['url']}` | `{r['vip_url']}` | {status_icon} | `{real_display}` |")
            md.append("")
    
    other_and_null = [r for r in results if 'other_domain' in r['issues'] or any(k.startswith('null_') for k in r['issues'])]
    if other_and_null:
        md.append("## 2. Detail Domain Lain / NULL\n")
        md.append("| ID | URL Asli (9tsu.in) | URL 9tsu.vip | DB `embed_url` | Real `embed_url` | Issues | Status |")
        md.append("| :---: | :--- | :--- | :--- | :--- | :--- | :---: |")
        for r in other_and_null:
            issues_str = ", ".join(r['issues'])
            status_icon = "✅" if r['status'] == 'verified' else ("❌" if r['status'] == 'mismatch' else "⚠️")
            real_display = r['real_embed'] if r['real_embed'] else f"Error: {r['error']}"
            md.append(f"| {r['id']} | `{r['url']}` | `{r['vip_url']}` | `{r['db_embed']}` | `{real_display}` | `{issues_str}` | {status_icon} |")
        md.append("")
    
    errors = [r for r in results if r['status'] == 'error']
    if errors:
        md.append("## 3. Error Scraping (9tsu.vip)\n")
        md.append("| ID | URL 9tsu.vip | DB `embed_url` | Error | Issues |")
        md.append("| :---: | :--- | :--- | :--- | :--- |")
        for r in errors:
            issues_str = ", ".join(r['issues'])
            md.append(f"| {r['id']} | `{r['vip_url']}` | `{r['db_embed']}` | `{r['error']}` | `{issues_str}` |")
        md.append("")
    
    md.append("## 📌 Ringkasan Akhir\n")
    md.append("| Metrik | Nilai |")
    md.append("| :--- | :---: |")
    md.append(f"| Total record mencurigakan | `{total}` |")
    md.append(f"| Cocok (valid) | `{verified}` |")
    md.append(f"| Tidak cocok (tidak valid) | `{mismatch}` |")
    md.append(f"| Error scraping | `{error_count}` |")
    if mismatch > 0:
        md.append("\n> ⚠️ **Perhatian:** Terdapat data yang tidak valid. Periksa detail di atas.")
    else:
        md.append("\n> ✅ **Semua data valid.**")
    
    filepath = os.path.join(REPORTS_DIR, OUTPUT_FILE)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    
    print("\n" + "=" * 60)
    print(f"📄 Laporan disimpan: {filepath}")
    print(f"   ✅ Cocok: {verified}")
    print(f"   ❌ Tidak cocok: {mismatch}")
    print(f"   ⚠️ Error: {error_count}")
    print("=" * 60)

if __name__ == "__main__":
    generate_report()
