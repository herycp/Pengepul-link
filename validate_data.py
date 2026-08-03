"""
validate_data.py
Validasi data dengan pendekatan efisien:
1. Satu query untuk semua data mencurigakan (duplikat, domain lain, NULL)
2. Verifikasi sampel (maks 10 per kategori) dengan scraping
3. Laporan ringkas Markdown
"""

import sqlite3
import os
import json
import cloudscraper
import time
from datetime import datetime
from urllib.parse import urlparse
from bs4 import BeautifulSoup

DB_FILE = "links.db"
REPORTS_DIR = "reports"
MAX_SAMPLE = 10  # Maksimal sampel per kategori untuk verifikasi

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "identity",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}

def ensure_reports_dir():
    if not os.path.exists(REPORTS_DIR):
        os.makedirs(REPORTS_DIR)

def get_suspicious_data():
    """
    Query tunggal untuk mendapatkan semua data mencurigakan.
    Return: dict dengan kategori
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
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
        ORDER BY embed_url, id
        LIMIT 100
    """)
    duplicates = cursor.fetchall()
    
    # 2. Domain di luar ok.ru dan pulvexa.space
    cursor.execute("""
        SELECT id, url, embed_url, embed_platform
        FROM links
        WHERE embed_url IS NOT NULL AND embed_url != ''
        AND embed_url NOT LIKE '%ok.ru%'
        AND embed_url NOT LIKE '%pulvexa.space%'
        LIMIT 100
    """)
    other_domains = cursor.fetchall()
    
    # 3. NULL values (semua field)
    fields = ['url', 'title', 'season', 'episode', 'image', 'description', 'embed_url', 'embed_platform']
    null_records = []
    for field in fields:
        cursor.execute(f"""
            SELECT id, url, embed_url, embed_platform, '{field}' as null_field
            FROM links
            WHERE {field} IS NULL OR {field} = ''
            LIMIT 20
        """)
        rows = cursor.fetchall()
        for row in rows:
            null_records.append({
                'id': row[0],
                'url': row[1],
                'embed_url': row[2],
                'embed_platform': row[3],
                'null_field': row[4]
            })
    
    conn.close()
    
    return {
        'duplicates': duplicates,
        'other_domains': other_domains,
        'nulls': null_records
    }

def scrape_embed(url):
    """Scrape halaman untuk mendapatkan embed_url yang sebenarnya"""
    try:
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
            delay=True,
            interpreter='native'
        )
        scraper.headers.update(HEADERS)
        response = scraper.get(url, timeout=60)
        if response.status_code != 200:
            return None, f"HTTP {response.status_code}"
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

def verify_sample(records, category):
    """Verifikasi sampel dengan scraping"""
    results = []
    for row in records[:MAX_SAMPLE]:
        if category == 'null':
            id_ = row['id']
            url = row['url']
            db_embed = row['embed_url']
            platform = row['embed_platform']
            null_field = row.get('null_field', 'unknown')
        else:
            id_, url, db_embed, platform = row
            null_field = None
        
        print(f"   🔍 Verifikasi ID {id_}...")
        real_embed, error = scrape_embed(url)
        
        results.append({
            'id': id_,
            'url': url,
            'db_embed': db_embed,
            'db_platform': platform,
            'real_embed': real_embed,
            'error': error,
            'null_field': null_field,
            'status': 'verified' if real_embed == db_embed else ('mismatch' if real_embed else 'error')
        })
        time.sleep(0.5)
    
    return results

def generate_report():
    """Generate laporan Markdown"""
    ensure_reports_dir()
    
    if not os.path.exists(DB_FILE):
        with open(os.path.join(REPORTS_DIR, "04_data_validation_report.md"), "w") as f:
            f.write("# ❌ Error\nlinks.db tidak ditemukan")
        return
    
    print("📡 Mengambil data mencurigakan...")
    data = get_suspicious_data()
    
    print(f"   - Duplikat: {len(data['duplicates'])} record")
    print(f"   - Domain lain: {len(data['other_domains'])} record")
    print(f"   - NULL: {len(data['nulls'])} record")
    
    # Verifikasi sampel
    print("\n🔍 Verifikasi sampel...")
    verified = {
        'duplicates': verify_sample(data['duplicates'], 'duplicate'),
        'other_domains': verify_sample(data['other_domains'], 'other_domain'),
        'nulls': verify_sample(data['nulls'], 'null')
    }
    
    # Buat laporan
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    md = []
    md.append("# 📋 Laporan Validasi Data\n")
    md.append(f"_Diperbarui: `{now}`_\n")
    
    # Ringkasan
    md.append("## 📊 Ringkasan\n")
    md.append("| Kategori | Total Ditemukan | Sampel Verifikasi |")
    md.append("| :--- | :---: | :---: |")
    md.append(f"| **Duplikat embed_url** | `{len(data['duplicates'])}` | `{len(verified['duplicates'])}` |")
    md.append(f"| **Domain di luar ok.ru/pulvexa** | `{len(data['other_domains'])}` | `{len(verified['other_domains'])}` |")
    md.append(f"| **NULL / kosong** | `{len(data['nulls'])}` | `{len(verified['nulls'])}` |\n")
    
    # Duplikat
    md.append("## 1. Duplikat `embed_url`\n")
    if data['duplicates']:
        md.append("| ID | URL Halaman | `embed_url` | `embed_platform` |")
        md.append("| :---: | :--- | :--- | :--- |")
        for row in data['duplicates'][:20]:
            id_, url, embed, platform = row
            url_short = url[:50] + "..." if len(url) > 50 else url
            md.append(f"| {id_} | `{url_short}` | `{embed}` | `{platform}` |")
        if len(data['duplicates']) > 20:
            md.append(f"| _... dan {len(data['duplicates'])-20} lainnya_ | | | |")
    else:
        md.append("> ✅ Tidak ada duplikat.\n")
    
    # Domain lain
    md.append("\n## 2. Domain di Luar `ok.ru` / `pulvexa.space`\n")
    if data['other_domains']:
        md.append("| ID | URL Halaman | `embed_url` | `embed_platform` |")
        md.append("| :---: | :--- | :--- | :--- |")
        for row in data['other_domains'][:20]:
            id_, url, embed, platform = row
            url_short = url[:50] + "..." if len(url) > 50 else url
            md.append(f"| {id_} | `{url_short}` | `{embed}` | `{platform}` |")
        if len(data['other_domains']) > 20:
            md.append(f"| _... dan {len(data['other_domains'])-20} lainnya_ | | | |")
    else:
        md.append("> ✅ Semua domain sesuai.\n")
    
    # NULL
    md.append("\n## 3. NULL / Kosong\n")
    if data['nulls']:
        md.append("| ID | URL Halaman | Field NULL | `embed_url` |")
        md.append("| :---: | :--- | :--- | :--- |")
        for rec in data['nulls'][:20]:
            url_short = rec['url'][:50] + "..." if len(rec['url']) > 50 else rec['url']
            embed = rec['embed_url'] or "*(null)*"
            md.append(f"| {rec['id']} | `{url_short}` | `{rec['null_field']}` | `{embed}` |")
        if len(data['nulls']) > 20:
            md.append(f"| _... dan {len(data['nulls'])-20} lainnya_ | | | |")
    else:
        md.append("> ✅ Tidak ada NULL.\n")
    
    # Hasil verifikasi
    md.append("\n## 4. Hasil Verifikasi Scraping (Sampel)\n")
    md.append("| Kategori | Status | Jumlah |")
    md.append("| :--- | :--- | :---: |")
    for cat, results in verified.items():
        ok = sum(1 for r in results if r['status'] == 'verified')
        mismatch = sum(1 for r in results if r['status'] == 'mismatch')
        error = sum(1 for r in results if r['status'] == 'error')
        md.append(f"| **{cat}** | ✅ Cocok | `{ok}` |")
        md.append(f"| **{cat}** | ❌ Tidak Cocok | `{mismatch}` |")
        md.append(f"| **{cat}** | ⚠️ Error Scraping | `{error}` |")
    
    # Detail mismatch
    mismatches = []
    for cat, results in verified.items():
        for r in results:
            if r['status'] == 'mismatch':
                mismatches.append({
                    'category': cat,
                    'id': r['id'],
                    'url': r['url'],
                    'db_embed': r['db_embed'],
                    'real_embed': r['real_embed']
                })
    
    if mismatches:
        md.append("\n### ❌ Detail Ketidakcocokan\n")
        md.append("| Kategori | ID | URL Halaman | DB `embed_url` | Real `embed_url` |")
        md.append("| :--- | :---: | :--- | :--- | :--- |")
        for m in mismatches:
            url_short = m['url'][:40] + "..." if len(m['url']) > 40 else m['url']
            md.append(f"| {m['category']} | {m['id']} | `{url_short}` | `{m['db_embed']}` | `{m['real_embed']}` |")
    
    # Simpan
    filepath = os.path.join(REPORTS_DIR, "04_data_validation_report.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    
    print(f"\n📄 Laporan disimpan: {filepath}")
    return filepath

if __name__ == "__main__":
    generate_report()
