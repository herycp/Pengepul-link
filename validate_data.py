"""
validate_data.py
Validasi data dengan pendekatan:
1. Query untuk mencari semua data mencurigakan (duplikat, domain lain, NULL)
2. Verifikasi SEMUA record tersebut dengan scraping halaman asli
3. Laporan detail hasil verifikasi
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

def get_all_suspicious_records():
    """
    Ambil SEMUA record yang termasuk dalam 3 kategori mencurigakan.
    Return: list of dict dengan field: id, url, embed_url, embed_platform, issue_type
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    suspicious = {}  # pakai dict agar id unik
    
    # 1. Duplikat embed_url (ambil semua record dari group yang duplikat)
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
            suspicious[id_] = {
                'id': id_,
                'url': url,
                'embed_url': embed,
                'embed_platform': platform,
                'issues': []
            }
        suspicious[id_]['issues'].append('duplicate')
    
    # 2. Domain di luar ok.ru dan pulvexa.space
    cursor.execute("""
        SELECT id, url, embed_url, embed_platform
        FROM links
        WHERE embed_url IS NOT NULL AND embed_url != ''
        AND embed_url NOT LIKE '%ok.ru%'
        AND embed_url NOT LIKE '%pulvexa.space%'
    """)
    for row in cursor.fetchall():
        id_, url, embed, platform = row
        if id_ not in suspicious:
            suspicious[id_] = {
                'id': id_,
                'url': url,
                'embed_url': embed,
                'embed_platform': platform,
                'issues': []
            }
        suspicious[id_]['issues'].append('other_domain')
    
    # 3. NULL values (semua field)
    fields = ['url', 'title', 'season', 'episode', 'image', 'description', 'embed_url', 'embed_platform']
    for field in fields:
        cursor.execute(f"""
            SELECT id, url, embed_url, embed_platform
            FROM links
            WHERE {field} IS NULL OR {field} = ''
        """)
        for row in cursor.fetchall():
            id_, url, embed, platform = row
            if id_ not in suspicious:
                suspicious[id_] = {
                    'id': id_,
                    'url': url,
                    'embed_url': embed,
                    'embed_platform': platform,
                    'issues': []
                }
            suspicious[id_]['issues'].append(f'null_{field}')
    
    conn.close()
    
    # Konversi ke list
    result = list(suspicious.values())
    print(f"🔍 Total record mencurigakan: {len(result)}")
    return result

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

def verify_record(record):
    """Verifikasi satu record dengan scraping"""
    real_embed, error = scrape_embed(record['url'])
    result = {
        'id': record['id'],
        'url': record['url'],
        'db_embed': record['embed_url'],
        'db_platform': record['embed_platform'],
        'issues': record['issues'],
        'real_embed': real_embed,
        'error': error,
        'status': 'verified' if real_embed == record['embed_url'] else ('mismatch' if real_embed else 'error')
    }
    return result

def generate_report():
    """Generate laporan Markdown"""
    ensure_reports_dir()
    
    if not os.path.exists(DB_FILE):
        with open(os.path.join(REPORTS_DIR, "04_data_validation_report.md"), "w") as f:
            f.write("# ❌ Error\nlinks.db tidak ditemukan")
        return
    
    print("📡 Mengambil semua data mencurigakan...")
    suspicious_records = get_all_suspicious_records()
    
    if not suspicious_records:
        print("✅ Tidak ada data mencurigakan!")
        with open(os.path.join(REPORTS_DIR, "04_data_validation_report.md"), "w") as f:
            f.write("# ✅ Laporan Validasi Data\n\n**Tidak ada data mencurigakan ditemukan.**")
        return
    
    print(f"🔍 Verifikasi {len(suspicious_records)} record dengan scraping...")
    results = []
    for i, rec in enumerate(suspicious_records, 1):
        print(f"   [{i}/{len(suspicious_records)}] ID {rec['id']}...")
        result = verify_record(rec)
        results.append(result)
        time.sleep(0.5)  # Jeda
    
    # Statistik
    total = len(results)
    verified = sum(1 for r in results if r['status'] == 'verified')
    mismatch = sum(1 for r in results if r['status'] == 'mismatch')
    error = sum(1 for r in results if r['status'] == 'error')
    
    # Kategorisasi issues
    issue_counts = {}
    for r in results:
        for issue in r['issues']:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1
    
    # Buat laporan
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    md = []
    md.append("# 📋 Laporan Validasi Data (Verifikasi Semua Record)\n")
    md.append(f"_Diperbarui: `{now}`_\n")
    
    md.append("## 📊 Ringkasan\n")
    md.append("| Kategori | Jumlah Record |")
    md.append("| :--- | :---: |")
    for issue, count in sorted(issue_counts.items()):
        md.append(f"| `{issue}` | `{count}` |")
    md.append("")
    
    md.append("## 🎯 Hasil Verifikasi Scraping\n")
    md.append("| Status | Jumlah | Persentase |")
    md.append("| :--- | :---: | :---: |")
    md.append(f"| ✅ Cocok | `{verified}` | `{verified/total*100:.1f}%` |")
    md.append(f"| ❌ Tidak Cocok | `{mismatch}` | `{mismatch/total*100:.1f}%` |")
    md.append(f"| ⚠️ Error Scraping | `{error}` | `{error/total*100:.1f}%` |")
    md.append("")
    
    # Detail semua record yang tidak cocok
    mismatches = [r for r in results if r['status'] == 'mismatch']
    if mismatches:
        md.append("## ❌ Detail Ketidakcocokan\n")
        md.append("| ID | URL Halaman | DB `embed_url` | Real `embed_url` | Issues |")
        md.append("| :---: | :--- | :--- | :--- | :--- |")
        for r in mismatches:
            url_short = r['url'][:40] + "..." if len(r['url']) > 40 else r['url']
            issues_str = ", ".join(r['issues'])
            md.append(f"| {r['id']} | `{url_short}` | `{r['db_embed']}` | `{r['real_embed']}` | `{issues_str}` |")
        md.append("")
    
    # Detail semua record yang error scraping
    errors = [r for r in results if r['status'] == 'error']
    if errors:
        md.append("## ⚠️ Error Scraping\n")
        md.append("| ID | URL Halaman | DB `embed_url` | Error | Issues |")
        md.append("| :---: | :--- | :--- | :--- | :--- |")
        for r in errors:
            url_short = r['url'][:40] + "..." if len(r['url']) > 40 else r['url']
            issues_str = ", ".join(r['issues'])
            md.append(f"| {r['id']} | `{url_short}` | `{r['db_embed']}` | `{r['error']}` | `{issues_str}` |")
        md.append("")
    
    # Detail semua record yang cocok (opsional, bisa dikomentari)
    if verified > 0 and verified <= 20:
        md.append("## ✅ Record yang Cocok\n")
        md.append("| ID | URL Halaman | `embed_url` |")
        md.append("| :---: | :--- | :--- |")
        for r in [r for r in results if r['status'] == 'verified']:
            url_short = r['url'][:40] + "..." if len(r['url']) > 40 else r['url']
            md.append(f"| {r['id']} | `{url_short}` | `{r['db_embed']}` |")
        md.append("")
    
    # Simpan
    filepath = os.path.join(REPORTS_DIR, "04_data_validation_report.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    
    print(f"\n📄 Laporan disimpan: {filepath}")
    print(f"   ✅ Cocok: {verified}")
    print(f"   ❌ Tidak cocok: {mismatch}")
    print(f"   ⚠️ Error: {error}")

if __name__ == "__main__":
    generate_report()
