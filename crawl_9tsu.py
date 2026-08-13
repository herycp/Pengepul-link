import cloudscraper
import xml.etree.ElementTree as ET
import json
import sqlite3
import re
import time
import os
import gzip
import subprocess
import concurrent.futures
from datetime import datetime
from urllib.parse import urlparse
from bs4 import BeautifulSoup

# ============================================================
# 1. KONFIGURASI
# ============================================================

BASE_URL = "https://9tsu.in"
SITEMAP_INDEX = f"{BASE_URL}/sitemap_index.xml"
DB_FILE = "links.db"
JSON_FILE = "links.json"
SITEMAP_DIR = "sitemaps"
BATCH_SIZE = 500
MAX_WORKERS = 15  # Eksekusi 15 download paralel bersamaan

ALTERNATIVE_DOMAINS = ["https://9tsu.vip", "https://9tsu.cc"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "identity",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
    "Referer": BASE_URL
}

# ============================================================
# 1.5 KONFIGURASI GLOBAL SCRAPER (PERBAIKAN PERFORMA)
# ============================================================
global_scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
    delay=True,
    interpreter='native'
)
global_scraper.headers.update(HEADERS)

# ============================================================
# 2. DATABASE SQLITE
# ============================================================

def init_database():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            title TEXT,
            season INTEGER,
            episode INTEGER,
            image TEXT,
            description TEXT,
            embed_url TEXT,
            embed_platform TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_url ON links(url)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_title ON links(title)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_season_episode ON links(season, episode)')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS processed_sitemaps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sitemap_file TEXT UNIQUE,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS processing_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sitemap_file TEXT UNIQUE,
            offset INTEGER DEFAULT 0,
            total INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

def reset_processing_state():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM processed_sitemaps')
    cursor.execute('DELETE FROM processing_state')
    conn.commit()
    conn.close()
    print("🔄 Status pemrosesan direset")

def is_all_sitemaps_processed():
    sitemap_files = get_sitemap_files()
    if not sitemap_files:
        return False
    processed = get_processed_sitemaps()
    return all(f in processed for f in sitemap_files)

def get_existing_urls(url_list):
    if not url_list:
        return [], []
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    placeholders = ','.join(['?'] * len(url_list))
    query = f"SELECT url FROM links WHERE url IN ({placeholders})"
    cursor.execute(query, url_list)
    existing = {row[0] for row in cursor.fetchall()}
    conn.close()
    new_urls = [url for url in url_list if url not in existing]
    return list(existing), new_urls

def save_to_database(metadata_list):
    if not metadata_list:
        return 0
    urls = [data.get('url') for data in metadata_list if data.get('url')]
    existing, new_urls = get_existing_urls(urls)
    if not new_urls:
        return 0
    new_data = [data for data in metadata_list if data.get('url') in new_urls]
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # BATCH INSERT (Memasukkan data sekaligus dalam satu transaksi)
    insert_payload = [
        (
            data.get('url'),
            data.get('title'),
            data.get('season'),
            data.get('episode'),
            data.get('image'),
            data.get('description'),
            data.get('embed_url'),
            data.get('embed_platform')
        )
        for data in new_data
    ]
    
    cursor.executemany('''
        INSERT OR IGNORE INTO links (url, title, season, episode, image, description, embed_url, embed_platform)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', insert_payload)
    
    new_count = cursor.rowcount
    conn.commit()
    conn.close()
    return new_count

def export_to_json():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT url, title, season, episode, image, description, embed_url, embed_platform, created_at FROM links')
    rows = cursor.fetchall()
    conn.close()
    links = []
    for row in rows:
        links.append({
            'url': row[0],
            'title': row[1],
            'season': row[2],
            'episode': row[3],
            'image': row[4],
            'description': row[5],
            'embed_url': row[6],
            'embed_platform': row[7],
            'created_at': row[8]
        })
    output = {'timestamp': datetime.now().isoformat(), 'total': len(links), 'links': links}
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

def get_database_count():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM links')
    count = cursor.fetchone()[0]
    conn.close()
    return count

# ============================================================
# 3. FUNGSI STATUS SITEMAP & PROGRESS
# ============================================================

def mark_sitemap_processed(sitemap_file):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO processed_sitemaps (sitemap_file) VALUES (?)', (sitemap_file,))
    cursor.execute('UPDATE processing_state SET status = "done" WHERE sitemap_file = ?', (sitemap_file,))
    conn.commit()
    conn.close()

def get_processed_sitemaps():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT sitemap_file FROM processed_sitemaps')
    rows = cursor.fetchall()
    conn.close()
    return {row[0] for row in rows}

def get_processing_state(sitemap_file):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT offset, total, status FROM processing_state WHERE sitemap_file = ?', (sitemap_file,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {'offset': row[0], 'total': row[1], 'status': row[2]}
    return None

def upsert_processing_state(sitemap_file, offset, total, status):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO processing_state (sitemap_file, offset, total, status, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(sitemap_file) DO UPDATE SET
            offset = excluded.offset,
            total = excluded.total,
            status = excluded.status,
            updated_at = CURRENT_TIMESTAMP
    ''', (sitemap_file, offset, total, status))
    conn.commit()
    conn.close()

def get_unprocessed_sitemaps():
    all_files = get_sitemap_files()
    if not all_files:
        return []
    processed = get_processed_sitemaps()
    result = []
    for f in all_files:
        if f in processed:
            continue
        state = get_processing_state(f)
        if state is None:
            urls = get_urls_from_local_sitemap(f)
            total = len(urls) if urls else 0
            if total > 0:
                upsert_processing_state(f, 0, total, 'pending')
                result.append((f, 0, total))
            else:
                mark_sitemap_processed(f)
        else:
            if state['status'] != 'done':
                result.append((f, state['offset'], state['total']))
    return result

def get_urls_from_local_sitemap(sitemap_filename):
    filepath = os.path.join(SITEMAP_DIR, sitemap_filename)
    if not os.path.exists(filepath):
        return []
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()
        ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        urls = []
        for loc in root.findall('.//ns:loc', ns):
            url = loc.text
            if url and (url.endswith('.html') or '/drama/' in url):
                urls.append(url)
        return urls
    except Exception:
        return []

def get_url_batch_from_sitemap(sitemap_file, offset, limit):
    all_urls = get_urls_from_local_sitemap(sitemap_file)
    if not all_urls:
        return [], 0, 0
    total = len(all_urls)
    if offset >= total:
        return [], total, total
    end = min(offset + limit, total)
    batch = all_urls[offset:end]
    return batch, end, total

# ============================================================
# 4. VERIFIKASI SITEMAP vs DATABASE
# ============================================================

def verify_sitemap_coverage():
    sitemap_files = get_sitemap_files()
    if not sitemap_files: return 0, 0
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    total_missing = 0
    reset_count = 0
    
    for f in sitemap_files:
        urls = get_urls_from_local_sitemap(f)
        if not urls: continue
        
        placeholders = ','.join(['?'] * len(urls))
        query = f"SELECT COUNT(*) FROM links WHERE url IN ({placeholders})"
        cursor.execute(query, urls)
        db_count = cursor.fetchone()[0]
        
        sitemap_count = len(urls)
        missing = sitemap_count - db_count
        state = get_processing_state(f)
        is_done = state and state['status'] == 'done'
        
        if missing > 0:
            if is_done:
                conn.execute("UPDATE processing_state SET status = 'pending', offset = 0, updated_at = CURRENT_TIMESTAMP WHERE sitemap_file = ?", (f,))
                reset_count += 1
            else:
                current_state = get_processing_state(f)
                if current_state:
                    if missing > 10 or current_state['offset'] == 0:
                        conn.execute("UPDATE processing_state SET offset = 0, updated_at = CURRENT_TIMESTAMP WHERE sitemap_file = ?", (f,))
                        reset_count += 1
            total_missing += missing
            
    conn.commit()
    conn.close()
    return total_missing, reset_count

# ============================================================
# 5. MANAJEMEN SITEMAP LOKAL & ONLINE
# ============================================================

def create_sitemap_dir():
    if not os.path.exists(SITEMAP_DIR):
        os.makedirs(SITEMAP_DIR)

def download_sitemap_with_cloudscraper(url, retry=3):
    for attempt in range(retry):
        try:
            response = global_scraper.get(url, timeout=60)
            if response.status_code == 200:
                return response.text, 200
            else:
                if attempt < retry - 1: time.sleep(2)
                else: return None, response.status_code
        except Exception:
            if attempt < retry - 1: time.sleep(2)
            else: return None, 0
    return None, 0

def get_sitemap_index_content():
    domains_to_try = [BASE_URL] + ALTERNATIVE_DOMAINS
    for domain in domains_to_try:
        try:
            sitemap_url = f"{domain}/sitemap_index.xml"
            response = global_scraper.get(sitemap_url, timeout=60)
            if response.status_code == 200:
                return response.content, domain
        except Exception:
            continue
    return None, None

def get_online_sitemap_list():
    content, domain = get_sitemap_index_content()
    if content is None: return []
    try:
        root = ET.fromstring(content)
        ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        sitemap_urls = []
        for loc in root.findall('.//ns:loc', ns):
            url = loc.text
            if url and 'post-sitemap' in url.lower():
                sitemap_urls.append(url)
        return sitemap_urls
    except Exception:
        return []

def download_all_sitemaps():
    create_sitemap_dir()
    for f in os.listdir(SITEMAP_DIR):
        if f.startswith('post-sitemap') and f.endswith('.xml'):
            os.remove(os.path.join(SITEMAP_DIR, f))
    online_urls = get_online_sitemap_list()
    if not online_urls: return
    for url in online_urls:
        filename = url.split('/')[-1]
        filepath = os.path.join(SITEMAP_DIR, filename)
        content, status = download_sitemap_with_cloudscraper(url)
        if status == 200 and content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
        time.sleep(0.5)

def get_sitemap_files():
    create_sitemap_dir()
    files = [f for f in os.listdir(SITEMAP_DIR) if f.startswith('post-sitemap') and f.endswith('.xml')]
    if not files: return []
    files.sort(key=lambda x: int(re.search(r'(\d+)', x).group(1)) if re.search(r'(\d+)', x) else 0)
    return files

# ============================================================
# 6. DOWNLOAD HTML
# ============================================================

def download_html_with_cloudscraper(url):
    try:
        response = global_scraper.get(url, timeout=30)
        if response.status_code == 200:
            raw = response.content
            if len(raw) >= 2 and raw[0] == 0x1F and raw[1] == 0x8B:
                try: raw = gzip.decompress(raw)
                except: pass
            try: html = raw.decode('utf-8')
            except: html = raw.decode('latin-1', errors='ignore')
            if html and len(html) > 100:
                return html, 200
            return None, 403
        else:
            return None, response.status_code
    except Exception:
        return None, 0

def download_html_with_curl(url):
    try:
        cmd = [
            'curl', '-s', '-L',
            '-H', f'User-Agent: {HEADERS["User-Agent"]}',
            '-H', 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9',
            '-H', 'Accept-Encoding: identity',
            '-H', 'Connection: keep-alive',
            '-H', 'Upgrade-Insecure-Requests: 1',
            '-H', f'Referer: {BASE_URL}',
            '--max-time', '30', url
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=35)
        if result.returncode == 0:
            content = result.stdout
            if len(content) >= 2 and content[0] == 0x1F and content[1] == 0x8B:
                try: content = gzip.decompress(content)
                except: pass
            try: html = content.decode('utf-8')
            except: html = content.decode('latin-1', errors='ignore')
            if html and len(html) > 100: return html, 200
            return None, 403
        return None, result.returncode
    except Exception:
        return None, 0

def download_html_page(url, retry=3):
    for attempt in range(retry):
        html, status = download_html_with_cloudscraper(url)
        if status == 200 and html: return html, 200
        if status == 403:
            time.sleep(2)
            continue
        if status != 403: break
    html, status = download_html_with_curl(url)
    if status == 200 and html: return html, 200
    return None, 403

# ============================================================
# 7. PARSING HTML
# ============================================================

def parse_html_page(html_content, url):
    metadata = {
        "url": url, "title": None, "season": None,
        "episode": None, "image": None, "description": None,
        "embed_url": None, "embed_platform": None
    }
    if not html_content: return metadata
    
    try:
        soup = BeautifulSoup(html_content, 'lxml') 
    except Exception:
        return metadata
    
    body_content = soup.find('div', class_='body-content') or soup.find('div', class_='hidden-content')
    if not body_content:
        return metadata

    raw_title = ""
    og_title = soup.find('meta', property='og:title')
    h1 = soup.find('h1')
    
    if og_title and og_title.get('content'):
        raw_title = og_title['content'].strip()
    elif h1:
        raw_title = h1.get_text(strip=True)
    elif soup.title:
        raw_title = soup.title.get_text(strip=True)

    if raw_title:
        metadata["season"] = 1
        metadata["episode"] = None

        match_s = re.search(r'(?:Season|シーズン)\s*(\d+)|第\s*(\d+)\s*(?:期|シリーズ|部)|[sS](\d+)', raw_title, re.IGNORECASE)
        if match_s:
            season_num = match_s.group(1) or match_s.group(2) or match_s.group(3)
            if season_num:
                metadata["season"] = int(season_num)

        match_e = re.search(r'(?:第|#|EP|ep)\s*(\d+)(?!\s*(?:期|シリーズ|部))\s*(?:話|回)?|[sS]\d+[eE](\d+)', raw_title, re.IGNORECASE)
        if match_e:
            episode_num = match_e.group(1) or match_e.group(2)
            if episode_num:
                metadata["episode"] = int(episode_num)

        cleaned = re.sub(r'(?:第|#|EP|ep)\s*\d+(?!\s*(?:期|シリーズ|部))\s*(?:話|回)?', '', raw_title, flags=re.IGNORECASE)
        cleaned = re.sub(r'(?:Season|シーズン)\s*\d+|第\s*\d+\s*(?:期|シリーズ|部)', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'[sS]\d+[eE]\d+', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s*[-|]\s*9tsu.*$', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s*[-|]\s*[Dd]ailymotion.*$', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s*[-|]\s*[Mm]iomio.*$', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s*[-|]\s*[Yy]outube.*$', '', cleaned, flags=re.IGNORECASE)
        
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        cleaned = re.sub(r'^[-|~]+\s*|\s*[-|~]+$', '', cleaned).strip()
        metadata["title"] = cleaned

    og_image = soup.find('meta', property='og:image')
    if og_image: metadata["image"] = og_image.get('content', '').strip()
    if body_content: metadata["description"] = body_content.get_text(separator=' ', strip=True)
    
    iframe = soup.find('iframe')
    if iframe and iframe.get('src'):
        embed_url = iframe['src'].strip()
        if embed_url.startswith('//'): embed_url = 'https:' + embed_url
        metadata["embed_url"] = embed_url
        metadata["embed_platform"] = urlparse(embed_url).netloc
    else:
        video = soup.find('video')
        if video:
            source = video.find('source')
            if source and source.get('src'):
                embed_url = source['src'].strip()
                if embed_url.startswith('//'): embed_url = 'https:' + embed_url
                metadata["embed_url"] = embed_url
                metadata["embed_platform"] = urlparse(embed_url).netloc
        else:
            for a in soup.find_all('a', href=True):
                href = a['href']
                if any(x in href for x in ['dailymotion', 'youtube', 'ok.ru', 'vimeo']):
                    embed_url = href.strip()
                    if embed_url.startswith('//'): embed_url = 'https:' + embed_url
                    metadata["embed_url"] = embed_url
                    metadata["embed_platform"] = urlparse(embed_url).netloc
                    break
    return metadata

def parse_html_with_regex(html_content, url):
    return parse_html_page(html_content, url)

# ============================================================
# 8. FUNGSI WORKER MULTI-THREADING
# ============================================================

def process_single_url(item):
    """Fungsi pekerja mandiri untuk mendownload dan mem-parsing 1 URL"""
    url, sitemap_file = item
    html_content, status = download_html_page(url)
    if status == 200 and html_content:
        metadata = parse_html_page(html_content, url)
        return metadata, status
    else:
        return {
            "url": url, "title": None, "season": None, "episode": None,
            "image": None, "description": None, "embed_url": None,
            "embed_platform": None
        }, status

# ============================================================
# 9. FUNGSI UTAMA
# ============================================================

def crawl_one_sitemap(force_download=False, reset=False, max_pages=None):
    init_database()
    if reset: reset_processing_state()
    total_missing, reset_count = verify_sitemap_coverage()
    
    if is_all_sitemaps_processed():
        reset_processing_state()
        download_all_sitemaps()
        for f in get_sitemap_files():
            all_urls = get_urls_from_local_sitemap(f)
            if all_urls: upsert_processing_state(f, 0, len(all_urls), 'pending')
    elif force_download:
        download_all_sitemaps()
        for f in get_sitemap_files():
            all_urls = get_urls_from_local_sitemap(f)
            if all_urls: upsert_processing_state(f, 0, len(all_urls), 'pending')
    
    sitemap_files = get_sitemap_files()
    if not sitemap_files:
        download_all_sitemaps()
        for f in get_sitemap_files():
            all_urls = get_urls_from_local_sitemap(f)
            if all_urls: upsert_processing_state(f, 0, len(all_urls), 'pending')
    
    unprocessed = get_unprocessed_sitemaps()
    if not unprocessed: return
    
    target_count = BATCH_SIZE
    if max_pages and max_pages < target_count: target_count = max_pages
    
    all_new_urls = []
    processed_sitemap_info = []
    remaining = target_count
    
    for sitemap_file, offset, total in unprocessed:
        if remaining <= 0: break
        while offset < total and remaining > 0:
            batch, new_offset, total_urls = get_url_batch_from_sitemap(sitemap_file, offset, remaining)
            if not batch:
                mark_sitemap_processed(sitemap_file)
                break
            existing, new_urls = get_existing_urls(batch)
            if new_urls:
                for url in new_urls: all_new_urls.append((url, sitemap_file))
                remaining -= len(new_urls)
                processed_sitemap_info.append({
                    'sitemap_file': sitemap_file, 'new_offset': new_offset,
                    'total': total_urls, 'taken': len(new_urls)
                })
            offset = new_offset
        if offset >= total: mark_sitemap_processed(sitemap_file)
        else: upsert_processing_state(sitemap_file, offset, total, 'pending')
    
    if not all_new_urls: 
        print("✅ Tidak ada URL baru untuk diproses.")
        return
    
    print(f"🚀 Memulai CRAWLING {len(all_new_urls)} link menggunakan Multi-Threading ({MAX_WORKERS} Workers)...")
    start_time = time.time()
    
    results = []
    # MULTI-THREADING EXECUTOR
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_single_url, item) for item in all_new_urls]
        for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
            metadata, status = future.result()
            results.append(metadata)
            if status == 200 and metadata.get('title'):
                print(f"[{i}/{len(all_new_urls)}] ✅ [{metadata.get('title')}] S{metadata.get('season')}E{metadata.get('episode')}")
            else:
                print(f"[{i}/{len(all_new_urls)}] ⚠️ Gagal/Invalid ({status}): {metadata.get('url')}")
    
    print("\n💾 Menyimpan hasil ke database secara massal...")
    new_count = save_to_database(results)
    
    for info in processed_sitemap_info:
        sitemap_file = info['sitemap_file']
        state = get_processing_state(sitemap_file)
        if state and state['status'] != 'done':
            if state['offset'] >= state['total']:
                mark_sitemap_processed(sitemap_file)
    
    export_to_json()
    elapsed = time.time() - start_time
    print(f"\n⏱️ Crawling Selesai! Waktu: {elapsed:.2f} detik ({elapsed/60:.2f} menit). {new_count} link baru disimpan.")

if __name__ == "__main__":
    import sys
    force_download = False
    reset = False
    max_pages = None
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i].lower()
        if arg == '--download': force_download = True
        elif arg == '--reset': reset = True
        elif arg == '--max-pages' and i + 1 < len(sys.argv):
            try:
                max_pages = int(sys.argv[i + 1])
                i += 1
            except: pass
        i += 1
    crawl_one_sitemap(force_download, reset, max_pages)
