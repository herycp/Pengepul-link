"""
validate_data.py
Memvalidasi data di database dengan:
1. Query untuk mencari data bermasalah (duplikat, domain lain, NULL)
2. Verifikasi dengan mengunjungi halaman asli (scraping)
3. Laporan per cycle (500 record)
Output: reports/validation/validation_*.json dan reports/validation/validation_summary.md
"""

import sqlite3
import os
import json
import requests
import cloudscraper
import re
from datetime import datetime
from urllib.parse import urlparse
from bs4 import BeautifulSoup

DB_FILE = "links.db"
REPORTS_DIR = "reports"
VALIDATION_DIR = os.path.join(REPORTS_DIR, "validation")
BATCH_SIZE = 500
MAX_VERIFY_PER_CYCLE = 10  # Maksimal 10 verifikasi per cycle untuk menghindari overload

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "identity",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}

def ensure_dirs():
    for d in [REPORTS_DIR, VALIDATION_DIR]:
        if not os.path.exists(d):
            os.makedirs(d)
            print(f"📁 Direktori dibuat: {d}")
    # Buat .gitkeep agar folder tidak kosong di git
    gitkeep = os.path.join(VALIDATION_DIR, ".gitkeep")
    if not os.path.exists(gitkeep):
        with open(gitkeep, 'w') as f:
            f.write("")
        print(f"📄 {gitkeep} dibuat")

def get_total_records():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM links")
    total = cursor.fetchone()[0]
    conn.close()
    return total

def get_batch_ids(start, limit):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM links ORDER BY id LIMIT ? OFFSET ?", (limit, start))
    ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    return ids

def scrape_page(url):
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
        # Cari iframe
        iframe = soup.find('iframe')
        if iframe and iframe.get('src'):
            embed_url = iframe['src'].strip()
            if embed_url.startswith('//'):
                embed_url = 'https:' + embed_url
            return embed_url, None
        # Cari link video
        for a in soup.find_all('a', href=True):
            href = a['href']
            if any(x in href for x in ['dailymotion', 'youtube', 'ok.ru', 'vimeo', 'pulvexa']):
                return href, None
        return None, "Tidak ditemukan embed"
    except Exception as e:
        return None, str(e)

def verify_record(record):
    """Verifikasi satu record dengan scraping"""
    record_id = record['id']
    page_url = record['url']
    db_embed = record['embed_url']
    db_platform = record.get('embed_platform')
    
    real_embed, error = scrape_page(page_url)
    if error:
        return {
            'id': record_id,
            'page_url': page_url,
            'db_embed': db_embed,
            'db_platform': db_platform,
            'real_embed': None,
            'status': 'error',
            'error': error
        }
    return {
        'id': record_id,
        'page_url': page_url,
        'db_embed': db_embed,
        'db_platform': db_platform,
        'real_embed': real_embed,
        'status': 'verified' if real_embed == db_embed else 'mismatch',
        'difference': None if real_embed == db_embed else {'db': db_embed, 'real': real_embed}
    }

def validate_batch(batch_ids, cycle_num, start, end):
    """Validasi satu batch dengan query dan verifikasi"""
    if not batch_ids:
        return None
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    id_list = ','.join(map(str, batch_ids))
    
    # 1. Duplikat embed_url
    cursor.execute(f"""
        SELECT id, url, embed_url, embed_platform
        FROM links
        WHERE id IN ({id_list})
          AND embed_url IS NOT NULL AND embed_url != ''
          AND embed_url IN (
              SELECT embed_url FROM links
              WHERE id IN ({id_list})
                AND embed_url IS NOT NULL AND embed_url != ''
              GROUP BY embed_url
              HAVING COUNT(*) > 1
          )
        ORDER BY embed_url
    """)
    duplicate_records = cursor.fetchall()
    
    # 2. Embed di luar domain
    cursor.execute(f"""
        SELECT id, url, embed_url, embed_platform
        FROM links
        WHERE id IN ({id_list})
          AND embed_url IS NOT NULL AND embed_url != ''
          AND embed_url NOT LIKE '%ok.ru%'
          AND embed_url NOT LIKE '%pulvexa.space%'
    """)
    other_domain_records = cursor.fetchall()
    
    # 3. NULL values
    fields = ['url', 'title', 'season', 'episode', 'image', 'description', 'embed_url', 'embed_platform']
    null_records = []
    for field in fields:
        cursor.execute(f"""
            SELECT id, url, embed_url, embed_platform
            FROM links
            WHERE id IN ({id_list})
              AND ({field} IS NULL OR {field} = '')
        """)
        rows = cursor.fetchall()
        for row in rows:
            null_records.append({
                'id': row[0],
                'url': row[1],
                'embed_url': row[2],
                'embed_platform': row[3],
                'null_field': field
            })
    
    conn.close()
    
    # Gabungkan semua record yang perlu diverifikasi (unik)
    verify_set = set()
    for row in duplicate_records:
        verify_set.add((row[0], row[1], row[2], row[3], 'duplicate'))
    for row in other_domain_records:
        verify_set.add((row[0], row[1], row[2], row[3], 'other_domain'))
    for rec in null_records:
        verify_set.add((rec['id'], rec['url'], rec['embed_url'], rec['embed_platform'], 'null'))
    
    # Konversi ke list of dict
    records_to_verify = []
    for id_, url, embed_url, platform, issue_type in list(verify_set)[:MAX_VERIFY_PER_CYCLE]:
        records_to_verify.append({
            'id': id_,
            'url': url,
            'embed_url': embed_url,
            'embed_platform': platform,
            'issue_type': issue_type
        })
    
    # Verifikasi dengan scraping (maks 10 per cycle)
    verification_results = []
    for rec in records_to_verify:
        print(f"   🔍 Verifikasi ID {rec['id']}...")
        result = verify_record(rec)
        if result:
            result['issue_type'] = rec['issue_type']
            verification_results.append(result)
        time.sleep(0.5)  # Jeda agar tidak kena blokir
    
    # Siapkan laporan per cycle
    report = {
        'cycle': cycle_num,
        'range': f"{start+1}-{end}",
        'timestamp': datetime.now().isoformat(),
        'total_in_batch': len(batch_ids),
        'issues': {
            'duplicate_count': len(duplicate_records),
            'other_domain_count': len(other_domain_records),
            'null_count': len(null_records)
        },
        'verification_results': verification_results,
        'summary': {
            'total_verified': len(verification_results),
            'verified_ok': sum(1 for r in verification_results if r.get('status') == 'verified'),
            'mismatch': sum(1 for r in verification_results if r.get('status') == 'mismatch'),
            'error': sum(1 for r in verification_results if r.get('status') == 'error')
        }
    }
    return report

def save_cycle_report(report):
    """Simpan laporan per cycle ke JSON"""
    filename = f"validation_cycle_{report['cycle']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    filepath = os.path.join(VALIDATION_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"📄 Laporan disimpan: {filepath}")
    return filepath

def generate_summary_report(all_reports):
    """Buat laporan ringkasan Markdown"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    md = []
    md.append("# 📋 Ringkasan Validasi Data\n")
    md.append(f"_Diperbarui: `{now}`_\n")
    
    total_verified = 0
    total_mismatch = 0
    total_error = 0
    total_ok = 0
    
    for rep in all_reports:
        total_verified += rep['summary']['total_verified']
        total_ok += rep['summary']['verified_ok']
        total_mismatch += rep['summary']['mismatch']
        total_error += rep['summary']['error']
    
    md.append(f"**Total record diverifikasi:** `{total_verified}`\n")
    md.append("| Status | Jumlah |")
    md.append("| :--- | :---: |")
    md.append(f"| ✅ Cocok | `{total_ok}` |")
    md.append(f"| ❌ Tidak Cocok | `{total_mismatch}` |")
    md.append(f"| ⚠️ Error Scraping | `{total_error}` |\n")
    
    if total_mismatch > 0:
        md.append("## ❌ Detail Ketidakcocokan\n")
        md.append("| ID | URL Halaman | DB `embed_url` | Real `embed_url` |")
        md.append("| :---: | :--- | :--- | :--- |")
        for rep in all_reports:
            for res in rep['verification_results']:
                if res.get('status') == 'mismatch':
                    md.append(f"| {res['id']} | [{res['page_url'][:40]}...]({res['page_url']}) | `{res['db_embed']}` | `{res['real_embed']}` |")
    
    summary_path = os.path.join(REPORTS_DIR, "validation_summary.md")
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(md))
    print(f"📄 Ringkasan disimpan: {summary_path}")
    return summary_path

def main():
    ensure_dirs()
    if not os.path.exists(DB_FILE):
        print("❌ links.db tidak ditemukan")
        return
    
    total = get_total_records()
    print(f"📊 Total record: {total}")
    print(f"📌 Batch size: {BATCH_SIZE} per cycle")
    print(f"📌 Maks verifikasi per cycle: {MAX_VERIFY_PER_CYCLE}")
    
    all_reports = []
    for start in range(0, total, BATCH_SIZE):
        end = min(start + BATCH_SIZE, total)
        cycle_num = (start // BATCH_SIZE) + 1
        print(f"\n{'='*50}")
        print(f"🔄 CYCLE {cycle_num}: record {start+1} - {end}")
        print(f"{'='*50}")
        
        batch_ids = get_batch_ids(start, BATCH_SIZE)
        if not batch_ids:
            break
        
        report = validate_batch(batch_ids, cycle_num, start, end)
        if report:
            save_cycle_report(report)
            all_reports.append(report)
            print(f"   ✅ Issues: duplikat={report['issues']['duplicate_count']}, "
                  f"domain lain={report['issues']['other_domain_count']}, "
                  f"NULL={report['issues']['null_count']}")
            print(f"   📊 Verifikasi: OK={report['summary']['verified_ok']}, "
                  f"mismatch={report['summary']['mismatch']}, error={report['summary']['error']}")
        else:
            print("   ℹ️ Tidak ada data di batch ini")
    
    if all_reports:
        generate_summary_report(all_reports)
        print("\n✅ Validasi selesai!")
    else:
        print("\n⚠️ Tidak ada laporan yang dihasilkan")

if __name__ == "__main__":
    import time
    main()
