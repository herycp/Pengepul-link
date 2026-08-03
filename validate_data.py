"""
validate_data.py
Validasi data dengan pendekatan:
1. Query untuk mencari semua data mencurigakan (duplikat, domain lain, NULL)
2. Verifikasi SEMUA record tersebut dengan scraping halaman asli
3. Laporan terstruktur per kategori:
   - Duplikat: dikelompokkan per embed_url, bandingkan validitas tiap record
   - Domain lain: tampilkan data dan hasil verifikasi
   - NULL: tampilkan data dan hasil verifikasi
"""

import sqlite3
import os
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

def get_suspicious_data():
    """Ambil semua record mencurigakan dengan query"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # 1. Duplikat embed_url (ambil semua record dari group duplikat)
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
    """)
    duplicates_raw = cursor.fetchall()
    
    # Kelompokkan duplikat
    duplicate_groups = {}
    for row in duplicates_raw:
        embed = row[2]
        if embed not in duplicate_groups:
            duplicate_groups[embed] = []
        duplicate_groups[embed].append({
            'id': row[0],
            'url': row[1],
            'embed_url': row[2],
            'embed_platform': row[3]
        })
    
    # 2. Domain di luar ok.ru dan pulvexa.space
    cursor.execute("""
        SELECT id, url, embed_url, embed_platform
        FROM links
        WHERE embed_url IS NOT NULL AND embed_url != ''
        AND embed_url NOT LIKE '%ok.ru%'
        AND embed_url NOT LIKE '%pulvexa.space%'
    """)
    other_domains = [{'id': r[0], 'url': r[1], 'embed_url': r[2], 'embed_platform': r[3]} for r in cursor.fetchall()]
    
    # 3. NULL values (semua field)
    fields = ['url', 'title', 'season', 'episode', 'image', 'description', 'embed_url', 'embed_platform']
    null_records = []
    for field in fields:
        cursor.execute(f"""
            SELECT id, url, embed_url, embed_platform
            FROM links
            WHERE {field} IS NULL OR {field} = ''
        """)
        for row in cursor.fetchall():
            null_records.append({
                'id': row[0],
                'url': row[1],
                'embed_url': row[2],
                'embed_platform': row[3],
                'null_field': field
            })
    
    conn.close()
    return duplicate_groups, other_domains, null_records

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
    return {
        'id': record['id'],
        'url': record['url'],
        'db_embed': record['embed_url'],
        'db_platform': record['embed_platform'],
        'real_embed': real_embed,
        'error': error,
        'valid': (real_embed == record['embed_url']) if real_embed else False
    }

def generate_report():
    ensure_reports_dir()
    
    if not os.path.exists(DB_FILE):
        with open(os.path.join(REPORTS_DIR, "04_data_validation_report.md"), "w") as f:
            f.write("# ❌ Error\nlinks.db tidak ditemukan")
        return
    
    print("📡 Mengambil data mencurigakan...")
    duplicate_groups, other_domains, null_records = get_suspicious_data()
    
    total_suspicious = sum(len(g) for g in duplicate_groups.values()) + len(other_domains) + len(null_records)
    if total_suspicious == 0:
        print("✅ Tidak ada data mencurigakan!")
        with open(os.path.join(REPORTS_DIR, "04_data_validation_report.md"), "w") as f:
            f.write("# ✅ Laporan Validasi Data\n\n**Tidak ada data mencurigakan ditemukan.**")
        return
    
    print(f"🔍 Verifikasi {total_suspicious} record dengan scraping...")
    
    # Verifikasi duplikat per grup
    verified_groups = {}
    for embed_url, records in duplicate_groups.items():
        verified_groups[embed_url] = []
        for rec in records:
            print(f"   Verifikasi ID {rec['id']} (duplikat)...")
            verified_groups[embed_url].append(verify_record(rec))
            time.sleep(0.5)
    
    # Verifikasi domain lain
    verified_other = []
    for rec in other_domains:
        print(f"   Verifikasi ID {rec['id']} (domain lain)...")
        verified_other.append(verify_record(rec))
        time.sleep(0.5)
    
    # Verifikasi NULL
    verified_null = []
    for rec in null_records:
        print(f"   Verifikasi ID {rec['id']} (NULL)...")
        verified_null.append(verify_record(rec))
        time.sleep(0.5)
    
    # ============================================================
    # Buat Laporan
    # ============================================================
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    md = []
    md.append("# 📋 Laporan Validasi Data (Verifikasi Semua Record)\n")
    md.append(f"_Diperbarui: `{now}`_\n")
    
    # ========== 1. DUPLIKAT ==========
    md.append("## 1. Duplikat `embed_url` (Per Kelompok)\n")
    if duplicate_groups:
        for embed_url, records in duplicate_groups.items():
            md.append(f"### Kelompok: `{embed_url}` (Total {len(records)} record)\n")
            md.append("| ID | URL Halaman | DB `embed_url` | Real `embed_url` | Status |")
            md.append("| :---: | :--- | :--- | :--- | :---: |")
            for rec in verified_groups.get(embed_url, []):
                url_short = rec['url'][:40] + "..." if len(rec['url']) > 40 else rec['url']
                db_embed = rec['db_embed']
                real_embed = rec['real_embed'] or "*(error)*"
                status = "✅ Valid" if rec['valid'] else ("❌ Tidak Valid" if rec['real_embed'] else "⚠️ Error")
                md.append(f"| {rec['id']} | `{url_short}` | `{db_embed}` | `{real_embed}` | {status} |")
            md.append("")
    else:
        md.append("> ✅ Tidak ada duplikat.\n")
    
    # ========== 2. DOMAIN LAIN ==========
    md.append("## 2. Domain di Luar `ok.ru` / `pulvexa.space`\n")
    if other_domains:
        md.append("| ID | URL Halaman | DB `embed_url` | Real `embed_url` | Status |")
        md.append("| :---: | :--- | :--- | :--- | :---: |")
        for rec in verified_other:
            url_short = rec['url'][:40] + "..." if len(rec['url']) > 40 else rec['url']
            db_embed = rec['db_embed']
            real_embed = rec['real_embed'] or "*(error)*"
            status = "✅ Valid" if rec['valid'] else ("❌ Tidak Valid" if rec['real_embed'] else "⚠️ Error")
            md.append(f"| {rec['id']} | `{url_short}` | `{db_embed}` | `{real_embed}` | {status} |")
        md.append("")
    else:
        md.append("> ✅ Semua domain sesuai.\n")
    
    # ========== 3. NULL ==========
    md.append("## 3. NULL / Kosong\n")
    if null_records:
        md.append("| ID | URL Halaman | Field NULL | DB `embed_url` | Real `embed_url` | Status |")
        md.append("| :---: | :--- | :--- | :--- | :--- | :---: |")
        # Map verified_null berdasarkan id untuk mencocokkan
        null_map = {r['id']: r for r in verified_null}
        for rec in null_records:
            ver = null_map.get(rec['id'])
            url_short = rec['url'][:40] + "..." if len(rec['url']) > 40 else rec['url']
            db_embed = rec['embed_url'] or "*(null)*"
            real_embed = ver['real_embed'] if ver and ver['real_embed'] else "*(null/error)*"
            status = "✅ Valid" if ver and ver['valid'] else ("❌ Tidak Valid" if ver and ver['real_embed'] else "⚠️ Error")
            md.append(f"| {rec['id']} | `{url_short}` | `{rec['null_field']}` | `{db_embed}` | `{real_embed}` | {status} |")
        md.append("")
    else:
        md.append("> ✅ Tidak ada NULL.\n")
    
    # ========== 4. RINGKASAN ==========
    md.append("## 4. Ringkasan\n")
    md.append("| Kategori | Jumlah Record | Valid | Tidak Valid | Error Scraping |")
    md.append("| :--- | :---: | :---: | :---: | :---: |")
    
    total_duplicates = sum(len(g) for g in duplicate_groups.values())
    valid_duplicates = sum(1 for g in verified_groups.values() for r in g if r['valid'])
    error_duplicates = sum(1 for g in verified_groups.values() for r in g if not r['real_embed'])
    invalid_duplicates = total_duplicates - valid_duplicates - error_duplicates
    
    md.append(f"| **Duplikat** | `{total_duplicates}` | `{valid_duplicates}` | `{invalid_duplicates}` | `{error_duplicates}` |")
    
    total_other = len(other_domains)
    valid_other = sum(1 for r in verified_other if r['valid'])
    error_other = sum(1 for r in verified_other if not r['real_embed'])
    invalid_other = total_other - valid_other - error_other
    md.append(f"| **Domain Lain** | `{total_other}` | `{valid_other}` | `{invalid_other}` | `{error_other}` |")
    
    total_null = len(null_records)
    valid_null = sum(1 for r in verified_null if r['valid'])
    error_null = sum(1 for r in verified_null if not r['real_embed'])
    invalid_null = total_null - valid_null - error_null
    md.append(f"| **NULL/Kosong** | `{total_null}` | `{valid_null}` | `{invalid_null}` | `{error_null}` |")
    
    md.append("")
    
    # Simpan
    filepath = os.path.join(REPORTS_DIR, "04_data_validation_report.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    
    print(f"\n📄 Laporan disimpan: {filepath}")
    print(f"   Total record diverifikasi: {total_suspicious}")
    print(f"   ✅ Valid: {valid_duplicates + valid_other + valid_null}")
    print(f"   ❌ Tidak Valid: {invalid_duplicates + invalid_other + invalid_null}")
    print(f"   ⚠️ Error Scraping: {error_duplicates + error_other + error_null}")

if __name__ == "__main__":
    generate_report()
