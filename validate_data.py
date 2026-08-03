"""
validate_data.py
Validasi data aktif:
1. Duplikat embed_url -> download halaman untuk verifikasi
2. Embed di luar ok.ru / pulvexa.space -> verifikasi dari halaman
3. NULL / kosong -> periksa halaman apakah benar tidak ada embed
Laporan per cycle (500 record) disimpan di reports/validation/
"""

import sqlite3
import json
import os
import shutil
import glob
import time
from datetime import datetime
from urllib.parse import urlparse
import requests
import cloudscraper

# ============================================================
# KONFIGURASI
# ============================================================
DB_FILE = "links.db"
REPORTS_DIR = "reports"
VALIDATION_DIR = os.path.join(REPORTS_DIR, "validation")
CYCLE_SIZE = 500  # Proses 500 record per cycle
TARGET_DOMAIN = "blogspherenews.xyz"
ALLOWED_DOMAINS = ["ok.ru", "pulvexa.space"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "identity",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# ============================================================
# FUNGSI BANTUAN
# ============================================================

def ensure_dirs():
    os.makedirs(VALIDATION_DIR, exist_ok=True)

def get_timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")

def get_iso_timestamp():
    return datetime.now().isoformat()

def get_iframe_from_page(url):
    """Download halaman dan ekstrak iframe/embed_url"""
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
        
        # Parse HTML
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Cari iframe
        iframe = soup.find('iframe')
        if iframe and iframe.get('src'):
            src = iframe['src'].strip()
            if src.startswith('//'):
                src = 'https:' + src
            elif src.startswith('/'):
                parsed = urlparse(url)
                src = f"{parsed.scheme}://{parsed.netloc}{src}"
            return src, None
        
        # Cari link video
        for a in soup.find_all('a', href=True):
            href = a['href']
            if any(x in href for x in ['dailymotion', 'youtube', 'ok.ru', 'vimeo']):
                return href, None
        
        return None, "No iframe/video found"
    except Exception as e:
        return None, str(e)

def extract_domain(url):
    if not url:
        return ""
    parsed = urlparse(url)
    netloc = parsed.netloc
    # hapus www.
    if netloc.startswith('www.'):
        netloc = netloc[4:]
    return netloc

def is_allowed_domain(url):
    domain = extract_domain(url)
    if not domain:
        return False
    return any(domain == d or domain.endswith('.' + d) for d in ALLOWED_DOMAINS)

# ============================================================
# 1. VALIDASI DUPLIKAT EMBED_URL
# ============================================================

def validate_duplicate_embeds(cycle_start, cycle_end):
    """
    Cari record yang memiliki embed_url sama,
    lalu download halaman untuk verifikasi.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Cari grup duplikat (hanya dalam range cycle)
    cursor.execute("""
        SELECT embed_url, GROUP_CONCAT(id) as ids, GROUP_CONCAT(url) as urls
        FROM (
            SELECT id, url, embed_url 
            FROM links 
            WHERE embed_url IS NOT NULL AND embed_url != '' 
              AND id BETWEEN ? AND ?
            ORDER BY id
        )
        GROUP BY embed_url
        HAVING COUNT(*) > 1
    """, (cycle_start, cycle_end))
    
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return None
    
    results = []
    for embed_url, ids_str, urls_str in rows:
        ids = ids_str.split(',')
        urls = urls_str.split(',')
        
        # Download setiap halaman untuk verifikasi
        verified_embeds = []
        for idx, (record_id, page_url) in enumerate(zip(ids, urls)):
            real_embed, error = get_iframe_from_page(page_url)
            verified_embeds.append({
                'id': int(record_id),
                'url': page_url,
                'real_embed': real_embed,
                'error': error
            })
        
        # Periksa apakah semua real_embed sama
        all_same = True
        first_embed = verified_embeds[0]['real_embed']
        for v in verified_embeds:
            if v['real_embed'] != first_embed:
                all_same = False
                break
        
        results.append({
            'embed_url': embed_url,
            'count': len(ids),
            'records': verified_embeds,
            'all_same': all_same,
            'first_embed': first_embed
        })
    
    return results

# ============================================================
# 2. VALIDASI EMBED DI LUAR DOMAIN
# ============================================================

def validate_outside_domain(cycle_start, cycle_end):
    """
    Cari record dengan embed_url di luar allowed domain,
    lalu verifikasi dari halaman.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, url, embed_url, embed_platform
        FROM links
        WHERE embed_url IS NOT NULL AND embed_url != ''
          AND id BETWEEN ? AND ?
          AND embed_url NOT LIKE '%ok.ru%'
          AND embed_url NOT LIKE '%pulvexa.space%'
        ORDER BY id
    """, (cycle_start, cycle_end))
    
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return None
    
    results = []
    for record_id, page_url, embed_url, embed_platform in rows:
        real_embed, error = get_iframe_from_page(page_url)
        # Cek apakah real_embed sesuai dengan embed_url di database
        is_correct = (real_embed == embed_url)
        results.append({
            'id': record_id,
            'url': page_url,
            'db_embed': embed_url,
            'db_platform': embed_platform,
            'real_embed': real_embed,
            'is_correct': is_correct,
            'error': error
        })
    
    return results

# ============================================================
# 3. VALIDASI NULL / KOSONG
# ============================================================

def validate_null_values(cycle_start, cycle_end):
    """
    Cari record dengan field NULL / kosong,
    lalu verifikasi apakah memang seharusnya NULL.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Semua field yang perlu dicek
    fields = ['url', 'title', 'season', 'episode', 'image', 'description', 'embed_url', 'embed_platform']
    
    results = {}
    null_records = {}
    
    for field in fields:
        cursor.execute(f"""
            SELECT id, url 
            FROM links 
            WHERE id BETWEEN ? AND ?
              AND ({field} IS NULL OR {field} = '')
            ORDER BY id
        """, (cycle_start, cycle_end))
        rows = cursor.fetchall()
        if rows:
            null_records[field] = rows
    
    conn.close()
    
    if not null_records:
        return None
    
    # Untuk setiap record yang punya NULL, verifikasi
    for field, records in null_records.items():
        verified = []
        for record_id, page_url in records:
            if field == 'embed_url':
                # Cek apakah halaman memang tidak punya embed
                real_embed, error = get_iframe_from_page(page_url)
                is_valid_null = (real_embed is None)
                verified.append({
                    'id': record_id,
                    'url': page_url,
                    'field': field,
                    'real_embed': real_embed,
                    'is_valid_null': is_valid_null,
                    'error': error
                })
            else:
                # Untuk field lain, cukup catat
                verified.append({
                    'id': record_id,
                    'url': page_url,
                    'field': field,
                    'is_valid_null': True,  # Tidak bisa verifikasi otomatis
                    'note': 'Manual verification needed'
                })
        results[field] = verified
    
    return results

# ============================================================
# 4. VALIDASI SATU URL (Debug)
# ============================================================

def validate_single_url(url):
    """Debug: verifikasi satu URL"""
    real_embed, error = get_iframe_from_page(url)
    print(f"🔍 Verifikasi: {url}")
    print(f"   Real embed: {real_embed}")
    print(f"   Error: {error}")
    return real_embed, error

# ============================================================
# 5. FUNGSI UTAMA - PROSES PER CYCLE
# ============================================================

def validate_cycle(cycle_start, cycle_end):
    """Proses validasi untuk satu cycle"""
    print(f"\n{'='*60}")
    print(f"📌 CYCLE: record {cycle_start} - {cycle_end}")
    print(f"{'='*60}")
    
    timestamp = get_timestamp()
    results = {}
    
    # 1. Duplikat
    print("🔍 Validasi duplikat embed_url...")
    dup_results = validate_duplicate_embeds(cycle_start, cycle_end)
    if dup_results:
        results['duplicate_embeds'] = dup_results
        print(f"   ✅ Ditemukan {len(dup_results)} grup duplikat")
    else:
        print("   ✅ Tidak ada duplikat")
    
    # 2. Outside domain
    print("🔍 Validasi embed di luar domain...")
    outside_results = validate_outside_domain(cycle_start, cycle_end)
    if outside_results:
        results['outside_domain'] = outside_results
        print(f"   ✅ Ditemukan {len(outside_results)} record")
    else:
        print("   ✅ Tidak ada embed di luar domain")
    
    # 3. NULL values
    print("🔍 Validasi NULL values...")
    null_results = validate_null_values(cycle_start, cycle_end)
    if null_results:
        results['null_values'] = null_results
        total_null = sum(len(v) for v in null_results.values())
        print(f"   ✅ Ditemukan {total_null} record dengan NULL")
    else:
        print("   ✅ Tidak ada NULL values")
    
    # Simpan laporan
    if results:
        report_file = os.path.join(VALIDATION_DIR, f"validation_{cycle_start}_{cycle_end}_{timestamp}.json")
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump({
                'timestamp': get_iso_timestamp(),
                'cycle': {'start': cycle_start, 'end': cycle_end},
                'results': results
            }, f, ensure_ascii=False, indent=2)
        print(f"📄 Laporan disimpan: {report_file}")
        return results
    else:
        print("✅ Tidak ada temuan dalam cycle ini.")
        return None

def validate_all():
    """Proses semua data per cycle"""
    ensure_dirs()
    
    if not os.path.exists(DB_FILE):
        print(f"❌ {DB_FILE} tidak ditemukan!")
        return
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT MIN(id), MAX(id) FROM links")
    min_id, max_id = cursor.fetchall()[0]
    conn.close()
    
    if min_id is None or max_id is None:
        print("❌ Database kosong!")
        return
    
    print(f"📊 Total record: {max_id} (ID: {min_id} - {max_id})")
    
    all_results = []
    for cycle_start in range(min_id, max_id + 1, CYCLE_SIZE):
        cycle_end = min(cycle_start + CYCLE_SIZE - 1, max_id)
        result = validate_cycle(cycle_start, cycle_end)
        if result:
            all_results.append(result)
        time.sleep(1)
    
    # Buat ringkasan
    generate_summary(all_results)
    print(f"\n🎉 Semua cycle selesai! {len(all_results)} cycle diproses.")

# ============================================================
# 6. GENERATE SUMMARY
# ============================================================

def generate_summary(results_list):
    """Buat ringkasan dari semua hasil validasi"""
    if not results_list:
        return
    
    summary = {
        'timestamp': get_iso_timestamp(),
        'total_cycles': len(results_list),
        'summary': {
            'duplicate_groups': 0,
            'duplicate_records': 0,
            'outside_domain_records': 0,
            'null_records': 0,
            'null_by_field': {}
        }
    }
    
    for result in results_list:
        # Duplikat
        if 'duplicate_embeds' in result:
            for dup in result['duplicate_embeds']:
                summary['summary']['duplicate_groups'] += 1
                summary['summary']['duplicate_records'] += dup['count']
        
        # Outside domain
        if 'outside_domain' in result:
            summary['summary']['outside_domain_records'] += len(result['outside_domain'])
        
        # NULL
        if 'null_values' in result:
            for field, records in result['null_values'].items():
                summary['summary']['null_records'] += len(records)
                if field not in summary['summary']['null_by_field']:
                    summary['summary']['null_by_field'][field] = 0
                summary['summary']['null_by_field'][field] += len(records)
    
    # Simpan summary
    timestamp = get_timestamp()
    summary_file = os.path.join(VALIDATION_DIR, f"summary_{timestamp}.md")
    
    md = []
    md.append("# 📊 Ringkasan Validasi Data\n")
    md.append(f"_Diperbarui: `{summary['timestamp']}`_\n")
    md.append(f"**Total cycle diproses:** `{summary['total_cycles']}`\n")
    
    md.append("## 📈 Temuan\n")
    md.append("| Kategori | Jumlah |")
    md.append("| :--- | :---: |")
    md.append(f"| **Grup duplikat embed_url** | `{summary['summary']['duplicate_groups']}` |")
    md.append(f"| **Record dalam grup duplikat** | `{summary['summary']['duplicate_records']}` |")
    md.append(f"| **Embed di luar domain** | `{summary['summary']['outside_domain_records']}` |")
    md.append(f"| **Record dengan NULL** | `{summary['summary']['null_records']}` |")
    
    if summary['summary']['null_by_field']:
        md.append("\n### NULL per Field\n")
        md.append("| Field | Jumlah |")
        md.append("| :--- | :---: |")
        for field, count in sorted(summary['summary']['null_by_field'].items(), key=lambda x: x[1], reverse=True):
            md.append(f"| `{field}` | `{count}` |")
    
    md.append("\n## 📂 Laporan Detail")
    md.append("Laporan per cycle tersimpan di folder `reports/validation/` dengan format JSON.")
    
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write("\n".join(md))
    
    print(f"📄 Ringkasan: {summary_file}")

# ============================================================
# 7. MAIN
# ============================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == '--all':
            validate_all()
        elif sys.argv[1] == '--cycle' and len(sys.argv) > 3:
            try:
                start = int(sys.argv[2])
                end = int(sys.argv[3])
                validate_cycle(start, end)
            except ValueError:
                print("❌ Gunakan: python validate_data.py --cycle <start> <end>")
        elif sys.argv[1] == '--url' and len(sys.argv) > 2:
            validate_single_url(sys.argv[2])
        else:
            print("❌ Argumen tidak dikenal.")
            print("\nPenggunaan:")
            print("  python validate_data.py --all")
            print("    - Proses semua data per cycle")
            print("  python validate_data.py --cycle <start> <end>")
            print("    - Proses satu cycle saja")
            print("  python validate_data.py --url <url>")
            print("    - Verifikasi satu URL")
    else:
        print("📡 Validasi Data - Mode Interaktif")
        print("Gunakan --all untuk memproses semua data.")