"""
validate_data.py
Memvalidasi data mencurigakan dengan scraping langsung dari website:
1. Duplikat embed_url: ambil 1 sampel dari setiap grup duplikat
2. Embed di luar domain: ambil semua (max 50)
3. NULL values: ambil sampel (max 50) untuk setiap field
Laporan: reports/04_data_validation_report.md
"""

import sqlite3
import os
import json
import time
from datetime import datetime
from urllib.parse import urlparse
import cloudscraper
from bs4 import BeautifulSoup

DB_FILE = "links.db"
REPORTS_DIR = "reports"
BATCH_SIZE = 50  # Maksimal per jenis validasi

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

def get_total_records():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM links")
    total = cursor.fetchone()[0]
    conn.close()
    return total

def get_iframe_from_html(html_content):
    """Ekstrak iframe dari HTML"""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        iframe = soup.find('iframe')
        if iframe and iframe.get('src'):
            src = iframe['src'].strip()
            if src.startswith('//'):
                src = 'https:' + src
            return src
        return None
    except:
        return None

def get_title_from_html(html_content):
    """Ekstrak title bersih dari HTML"""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        # Coba dari article:section
        meta = soup.find('meta', property='article:section')
        if meta and meta.get('content'):
            return meta['content'].strip()
        # Coba dari og:title
        meta = soup.find('meta', property='og:title')
        if meta and meta.get('content'):
            return meta['content'].strip()
        # Coba dari h1
        h1 = soup.find('h1')
        if h1:
            return h1.get_text(strip=True)
        # Coba dari title
        title = soup.find('title')
        if title:
            return title.get_text(strip=True)
        return None
    except:
        return None

def scrape_page(url, retry=2):
    """Download dan ekstrak metadata dari halaman"""
    for attempt in range(retry):
        try:
            scraper = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
                delay=True,
                interpreter='native'
            )
            scraper.headers.update(HEADERS)
            response = scraper.get(url, timeout=45)
            if response.status_code != 200:
                continue
            html = response.text
            return {
                'title': get_title_from_html(html),
                'embed_url': get_iframe_from_html(html),
                'status_code': 200,
                'html_size': len(html)
            }
        except Exception as e:
            print(f"   ⚠️ Attempt {attempt+1} failed: {e}")
            time.sleep(2)
    return {
        'title': None,
        'embed_url': None,
        'status_code': 0,
        'html_size': 0,
        'error': 'Scrape failed'
    }

def validate_with_verification():
    """
    1. Cari record mencurigakan dengan query
    2. Verifikasi dengan scraping langsung
    3. Buat laporan perbedaan
    """
    ensure_reports_dir()
    if not os.path.exists(DB_FILE):
        print("❌ links.db tidak ditemukan")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # ============================================================
    # 1. Ambil sampel duplikat embed_url (1 per grup)
    # ============================================================
    cursor.execute("""
        SELECT embed_url, GROUP_CONCAT(id) as ids, COUNT(*) as cnt
        FROM links
        WHERE embed_url IS NOT NULL AND embed_url != ''
        GROUP BY embed_url
        HAVING COUNT(*) > 1
        ORDER BY cnt DESC
        LIMIT 20
    """)
    duplicate_groups = cursor.fetchall()
    duplicate_samples = []
    for dup_url, ids_str, cnt in duplicate_groups:
        ids = ids_str.split(',')
        # ambil ID pertama dari grup
        sample_id = ids[0]
        cursor.execute("SELECT url, title, embed_platform FROM links WHERE id = ?", (sample_id,))
        row = cursor.fetchone()
        if row:
            duplicate_samples.append({
                'id': int(sample_id),
                'url': row[0],
                'title_db': row[1],
                'embed_url_db': dup_url,
                'embed_platform_db': row[2],
                'duplicate_count': cnt,
                'duplicate_ids': ids_str
            })

    # ============================================================
    # 2. Ambil embed di luar domain (max 30)
    # ============================================================
    cursor.execute("""
        SELECT id, url, title, embed_url, embed_platform
        FROM links
        WHERE embed_url IS NOT NULL
          AND embed_url != ''
          AND embed_url NOT LIKE '%ok.ru%'
          AND embed_url NOT LIKE '%pulvexa.space%'
        LIMIT 30
    """)
    other_domain_records = cursor.fetchall()
    other_domain_samples = [
        {
            'id': row[0],
            'url': row[1],
            'title_db': row[2],
            'embed_url_db': row[3],
            'embed_platform_db': row[4]
        }
        for row in other_domain_records
    ]

    # ============================================================
    # 3. Ambil sampel NULL values (max 30 per field)
    # ============================================================
    null_fields = ['title', 'image', 'description', 'embed_url', 'embed_platform']
    null_samples = {}
    for field in null_fields:
        cursor.execute(f"""
            SELECT id, url, title, embed_url, embed_platform
            FROM links
            WHERE {field} IS NULL OR {field} = ''
            LIMIT 10
        """)
        rows = cursor.fetchall()
        if rows:
            null_samples[field] = [
                {
                    'id': row[0],
                    'url': row[1],
                    'title_db': row[2],
                    'embed_url_db': row[3],
                    'embed_platform_db': row[4],
                    'null_field': field
                }
                for row in rows
            ]

    conn.close()

    # ============================================================
    # 4. Verifikasi dengan scraping
    # ============================================================
    print("🔍 Memulai verifikasi data mencurigakan...")
    print(f"   - Duplikat: {len(duplicate_samples)} sampel")
    print(f"   - Domain lain: {len(other_domain_samples)} record")
    null_total = sum(len(v) for v in null_samples.values())
    print(f"   - NULL: {null_total} sampel")
    print("")

    all_issues = []

    # 4a. Verifikasi duplikat
    for idx, sample in enumerate(duplicate_samples, 1):
        print(f"📌 [{idx}/{len(duplicate_samples)}] Duplikat: {sample['url']}")
        scraped = scrape_page(sample['url'])
        if scraped.get('status_code') == 200:
            sample['title_scraped'] = scraped.get('title')
            sample['embed_url_scraped'] = scraped.get('embed_url')
            # Cek apakah nilai scraped sama dengan DB
            if sample['title_db'] != sample['title_scraped']:
                sample['title_mismatch'] = True
            else:
                sample['title_mismatch'] = False
            if sample['embed_url_db'] != sample['embed_url_scraped']:
                sample['embed_mismatch'] = True
                # Tambahkan ke isu
                all_issues.append({
                    'type': 'duplicate_mismatch',
                    'id': sample['id'],
                    'url': sample['url'],
                    'field': 'embed_url',
                    'db_value': sample['embed_url_db'],
                    'scraped_value': sample['embed_url_scraped']
                })
            else:
                sample['embed_mismatch'] = False
        else:
            sample['scrape_error'] = True
            sample['title_scraped'] = None
            sample['embed_url_scraped'] = None
        time.sleep(0.5)

    # 4b. Verifikasi domain lain
    for idx, sample in enumerate(other_domain_samples, 1):
        print(f"📌 [{idx}/{len(other_domain_samples)}] Domain lain: {sample['url']}")
        scraped = scrape_page(sample['url'])
        if scraped.get('status_code') == 200:
            sample['title_scraped'] = scraped.get('title')
            sample['embed_url_scraped'] = scraped.get('embed_url')
            if sample['embed_url_db'] != sample['embed_url_scraped']:
                sample['embed_mismatch'] = True
                all_issues.append({
                    'type': 'other_domain_mismatch',
                    'id': sample['id'],
                    'url': sample['url'],
                    'field': 'embed_url',
                    'db_value': sample['embed_url_db'],
                    'scraped_value': sample['embed_url_scraped']
                })
            else:
                sample['embed_mismatch'] = False
        else:
            sample['scrape_error'] = True
        time.sleep(0.5)

    # 4c. Verifikasi NULL
    for field, samples in null_samples.items():
        for idx, sample in enumerate(samples, 1):
            print(f"📌 NULL [{field}] {sample['url']}")
            scraped = scrape_page(sample['url'])
            if scraped.get('status_code') == 200:
                sample['title_scraped'] = scraped.get('title')
                sample['embed_url_scraped'] = scraped.get('embed_url')
                # Cek apakah field yang null ternyata ada di scraped
                if field == 'title' and scraped.get('title') is not None:
                    all_issues.append({
                        'type': 'null_should_have_value',
                        'id': sample['id'],
                        'url': sample['url'],
                        'field': field,
                        'db_value': None,
                        'scraped_value': scraped.get('title')
                    })
                if field == 'embed_url' and scraped.get('embed_url') is not None:
                    all_issues.append({
                        'type': 'null_should_have_value',
                        'id': sample['id'],
                        'url': sample['url'],
                        'field': field,
                        'db_value': None,
                        'scraped_value': scraped.get('embed_url')
                    })
            else:
                sample['scrape_error'] = True
            time.sleep(0.5)

    # ============================================================
    # 5. Buat laporan
    # ============================================================
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    total_records = get_total_records()

    md = []
    md.append("# 📋 Laporan Validasi Data (Verifikasi Langsung)\n")
    md.append(f"_Diperbarui: `{now}`_\n")
    md.append(f"**Total record di database:** `{total_records}`\n")

    # Ringkasan
    md.append("## 📊 Ringkasan Verifikasi\n")
    md.append("| Kategori | Sampel Diverifikasi | Masalah Ditemukan |")
    md.append("| :--- | :---: | :---: |")
    md.append(f"| **Duplikat embed_url** | `{len(duplicate_samples)}` | `{len([s for s in duplicate_samples if s.get('embed_mismatch')])}` |")
    md.append(f"| **Domain tidak dikenal** | `{len(other_domain_samples)}` | `{len([s for s in other_domain_samples if s.get('embed_mismatch')])}` |")
    md.append(f"| **NULL values** | `{null_total}` | `{len([i for i in all_issues if i['type'] == 'null_should_have_value'])}` |")
    md.append("")

    # Detail isu
    if all_issues:
        md.append("## ⚠️ Detail Masalah yang Ditemukan\n")
        md.append("| ID | Jenis | URL | Field | Nilai di DB | Nilai Scraped |")
        md.append("| :---: | :--- | :--- | :--- | :--- | :--- |")
        for issue in all_issues[:50]:
            url_short = issue['url'][:50] + "..." if len(issue['url']) > 50 else issue['url']
            db_val = issue['db_value'][:50] + "..." if issue['db_value'] and len(issue['db_value']) > 50 else issue['db_value']
            scraped_val = issue['scraped_value'][:50] + "..." if issue['scraped_value'] and len(issue['scraped_value']) > 50 else issue['scraped_value']
            md.append(f"| {issue['id']} | `{issue['type']}` | `{url_short}` | `{issue['field']}` | `{db_val}` | `{scraped_val}` |")
    else:
        md.append("## ✅ Semua Data Terverifikasi\n")
        md.append("> Tidak ditemukan ketidaksesuaian antara data di database dengan hasil scraping langsung.\n")

    # Simpan
    report_path = os.path.join(REPORTS_DIR, "04_data_validation_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"\n📄 Laporan validasi dibuat: {report_path}")

if __name__ == "__main__":
    validate_with_verification()
