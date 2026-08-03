import cloudscraper
import xml.etree.ElementTree as ET
import json
import sqlite3
import re
import time
import os
import gzip
import subprocess
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
BATCH_SIZE = 500  # Total link per run dari semua sitemap

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
    print("✅ Database siap")

def reset_processing_state():
    """Reset semua status pemrosesan (processed_sitemaps & processing_state)"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM processed_sitemaps')
    cursor.execute('DELETE FROM processing_state')
    conn.commit()
    conn.close()
    print("🔄 Status pemrosesan direset (semua sitemap akan diproses ulang)")

def is_all_sitemaps_processed():
    """Cek apakah semua sitemap lokal sudah diproses (status done)"""
    sitemap_files = get_sitemap_files()
    if not sitemap_files:
        return False
    processed = get_processed_sitemaps()
    return all(f in processed for f in sitemap_files)

def is_url_exists(url):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM links WHERE url = ?", (url,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def get_existing_urls(url_list):
    """Filter URL yang sudah ada di database"""
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
    new_count = 0
    for data in new_data:
        cursor.execute('''
            INSERT INTO links (url, title, season, episode, image, description, embed_url, embed_platform)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data.get('url'),
            data.get('title'),
            data.get('season'),
            data.get('episode'),
            data.get('image'),
            data.get('description'),
            data.get('embed_url'),
            data.get('embed_platform')
        ))
        new_count += 1
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
    print(f"📁 JSON ekspor: {len(links)} link")

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
    """
    Ambil semua sitemap yang belum selesai (status != 'done'), urutkan ascending.
    Return: list of (sitemap_file, offset, total)
    """
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
            # Belum ada state, buat baru dengan offset 0
            urls = get_urls_from_local_sitemap(f)
            total = len(urls) if urls else 0
            if total > 0:
                upsert_processing_state(f, 0, total, 'pending')
                result.append((f, 0, total))
            else:
                # Tidak ada URL, tandai selesai
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
    except Exception as e:
        print(f"❌ Error parsing sitemap lokal {sitemap_filename}: {e}")
        return []

def get_url_batch_from_sitemap(sitemap_file, offset, limit):
    """
    Ambil sejumlah URL dari sitemap mulai dari offset, maksimal limit.
    Return: (batch_urls, new_offset, total_urls_in_sitemap)
    """
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
# 4. MANAJEMEN SITEMAP LOKAL & ONLINE
# ============================================================

def create_sitemap_dir():
    if not os.path.exists(SITEMAP_DIR):
        os.makedirs(SITEMAP_DIR)
        print(f"📁 Direktori sitemap dibuat: {SITEMAP_DIR}")

def download_sitemap_with_cloudscraper(url, retry=3):
    for attempt in range(retry):
        try:
            scraper = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
                delay=True,
                interpreter='native'
            )
            scraper.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
                "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept-Encoding": "identity",
                "Connection": "keep-alive",
                "Cache-Control": "max-age=0",
            })
            response = scraper.get(url, timeout=60)
            if response.status_code == 200:
                return response.text, 200
            else:
                print(f"   ⚠️ Attempt {attempt+1}/{retry} - Status: {response.status_code}")
                if attempt < retry - 1:
                    time.sleep(2)
                else:
                    return None, response.status_code
        except Exception as e:
            print(f"   ⚠️ Attempt {attempt+1}/{retry} - Error: {e}")
            if attempt < retry - 1:
                time.sleep(2)
            else:
                return None, 0
    return None, 0

def get_sitemap_index_content():
    domains_to_try = [BASE_URL] + ALTERNATIVE_DOMAINS
    for domain in domains_to_try:
        try:
            sitemap_url = f"{domain}/sitemap_index.xml"
            print(f"🔄 Mencoba: {sitemap_url}")
            scraper = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
                delay=True,
                interpreter='native'
            )
            scraper.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
                "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept-Encoding": "identity",
                "Connection": "keep-alive",
                "Cache-Control": "max-age=0",
            })
            response = scraper.get(sitemap_url, timeout=60)
            if response.status_code == 200:
                print(f"✅ Berhasil menggunakan domain: {domain}")
                return response.content, domain
            else:
                print(f"   ❌ Gagal: HTTP {response.status_code}")
        except Exception as e:
            print(f"   ❌ Gagal: {e}")
            continue
    return None, None

def get_online_sitemap_list():
    content, domain = get_sitemap_index_content()
    if content is None:
        return []
    try:
        root = ET.fromstring(content)
        ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        sitemap_urls = []
        for loc in root.findall('.//ns:loc', ns):
            url = loc.text
            if url and 'post-sitemap' in url.lower():
                sitemap_urls.append(url)
        return sitemap_urls
    except Exception as e:
        print(f"❌ Error parsing online sitemap index: {e}")
        return []

def download_all_sitemaps():
    create_sitemap_dir()
    for f in os.listdir(SITEMAP_DIR):
        if f.startswith('post-sitemap') and f.endswith('.xml'):
            os.remove(os.path.join(SITEMAP_DIR, f))
            print(f"🗑️  Hapus: {f}")
    online_urls = get_online_sitemap_list()
    if not online_urls:
        print("❌ Gagal mendapatkan daftar sitemap online.")
        return
    for url in online_urls:
        filename = url.split('/')[-1]
        filepath = os.path.join(SITEMAP_DIR, filename)
        print(f"⬇️  Download {filename}")
        content, status = download_sitemap_with_cloudscraper(url)
        if status == 200 and content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"   ✅ Tersimpan: {filepath}")
        else:
            print(f"   ❌ Gagal download {filename}")
        time.sleep(0.5)
    print("✅ Semua sitemap selesai diunduh")

def get_sitemap_files():
    create_sitemap_dir()
    files = [f for f in os.listdir(SITEMAP_DIR) if f.startswith('post-sitemap') and f.endswith('.xml')]
    if not files:
        return []
    files.sort(key=lambda x: int(re.search(r'(\d+)', x).group(1)) if re.search(r'(\d+)', x) else 0)
    return files

# ============================================================
# 5. DOWNLOAD HTML
# ============================================================

def download_html_with_cloudscraper(url):
    try:
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
            delay=True,
            interpreter='native'
        )
        scraper.headers.update(HEADERS)
        response = scraper.get(url, timeout=60)
        if response.status_code == 200:
            raw = response.content
            if len(raw) >= 2 and raw[0] == 0x1F and raw[1] == 0x8B:
                try:
                    raw = gzip.decompress(raw)
                except:
                    pass
            try:
                html = raw.decode('utf-8')
            except:
                html = raw.decode('latin-1', errors='ignore')
            if html and len(html) > 100 and any(tag in html[:200] for tag in ['<html', '<!DOCTYPE', '<title', '<body']):
                return html, 200
            else:
                try:
                    response.encoding = 'utf-8'
                    html2 = response.text
                    if html2 and len(html2) > 100 and any(tag in html2[:200] for tag in ['<html', '<!DOCTYPE', '<title', '<body']):
                        return html2, 200
                except:
                    pass
                return None, 403
        else:
            return None, response.status_code
    except Exception as e:
        print(f"   ❌ Cloudscraper error: {e}")
        return None, 0

def download_html_with_curl(url):
    try:
        cmd = [
            'curl', '-s', '-L',
            '-H', f'User-Agent: {HEADERS["User-Agent"]}',
            '-H', 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9',
            '-H', 'Accept-Language: id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7',
            '-H', 'Accept-Encoding: identity',
            '-H', 'Connection: keep-alive',
            '-H', 'Upgrade-Insecure-Requests: 1',
            '-H', f'Referer: {BASE_URL}',
            '--max-time', '30',
            url
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=35)
        if result.returncode == 0:
            content = result.stdout
            if len(content) >= 2 and content[0] == 0x1F and content[1] == 0x8B:
                try:
                    content = gzip.decompress(content)
                except:
                    pass
            try:
                html = content.decode('utf-8')
            except:
                html = content.decode('latin-1', errors='ignore')
            if html and len(html) > 100 and any(tag in html[:200] for tag in ['<html', '<!DOCTYPE', '<title', '<body']):
                return html, 200
            else:
                return None, 403
        else:
            return None, result.returncode
    except Exception as e:
        print(f"   ❌ Curl error: {e}")
        return None, 0

def download_html_page(url, retry=3):
    for attempt in range(retry):
        html, status = download_html_with_cloudscraper(url)
        if status == 200 and html:
            return html, 200
        if status == 403:
            time.sleep(3 + attempt * 2)
            continue
        if status != 403:
            break
    html, status = download_html_with_curl(url)
    if status == 200 and html:
        return html, 200
    return None, 403

# ============================================================
# 6. PARSING HTML (sama seperti sebelumnya)
# ============================================================

def parse_html_page(html_content, url):
    metadata = {
        "url": url,
        "title": None,
        "season": None,
        "episode": None,
        "image": None,
        "description": None,
        "embed_url": None,
        "embed_platform": None
    }
    if not html_content:
        return metadata
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
    except Exception as e:
        print(f"   ⚠️ BeautifulSoup error: {e}")
        return parse_html_with_regex(html_content, url)
    # --- TITLE ---
    article_section = soup.find('meta', property='article:section')
    if article_section and article_section.get('content'):
        metadata["title"] = article_section['content'].strip()
    else:
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            raw = og_title['content'].strip()
            cleaned = re.sub(r'\s*第\d+話\s*', '', raw)
            cleaned = re.sub(r'\s*Season\s*\d+\s*', '', cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r'\s*[-|]\s*9tsu.*$', '', cleaned)
            cleaned = re.sub(r'\s*[-|]\s*[Dd]ailymotion.*$', '', cleaned)
            cleaned = re.sub(r'\s*[-|]\s*[Mm]iomio.*$', '', cleaned)
            cleaned = re.sub(r'\s*[-|]\s*[Yy]outube.*$', '', cleaned)
            metadata["title"] = cleaned.strip()
        else:
            h1 = soup.find('h1')
            if h1:
                raw = h1.get_text(strip=True)
                cleaned = re.sub(r'\s*第\d+話\s*', '', raw)
                cleaned = re.sub(r'\s*Season\s*\d+\s*', '', cleaned, flags=re.IGNORECASE)
                metadata["title"] = cleaned.strip()
            else:
                title_tag = soup.find('title')
                if title_tag:
                    raw = title_tag.get_text(strip=True)
                    cleaned = re.sub(r'\s*第\d+話\s*', '', raw)
                    cleaned = re.sub(r'\s*Season\s*\d+\s*', '', cleaned, flags=re.IGNORECASE)
                    cleaned = re.sub(r'\s*[-|]\s*9tsu.*$', '', cleaned)
                    cleaned = re.sub(r'\s*[-|]\s*[Dd]ailymotion.*$', '', cleaned)
                    cleaned = re.sub(r'\s*[-|]\s*[Mm]iomio.*$', '', cleaned)
                    cleaned = re.sub(r'\s*[-|]\s*[Yy]outube.*$', '', cleaned)
                    metadata["title"] = cleaned.strip()
    # --- SEASON & EPISODE ---
    text = soup.get_text()
    match = re.search(r'Season\s*(\d+)\s*[　]?\s*第(\d+)話', text, re.IGNORECASE)
    if match:
        metadata["season"] = int(match.group(1))
        metadata["episode"] = int(match.group(2))
    else:
        match = re.search(r'第(\d+)話', text)
        if match:
            metadata["season"] = 1
            metadata["episode"] = int(match.group(1))
        else:
            match = re.search(r'[sS](\d+)[eE](\d+)', text)
            if match:
                metadata["season"] = int(match.group(1))
                metadata["episode"] = int(match.group(2))
    # --- IMAGE ---
    og_image = soup.find('meta', property='og:image')
    if og_image and og_image.get('content'):
        metadata["image"] = og_image['content'].strip()
    # --- DESCRIPTION ---
    body_content = soup.find('div', class_='body-content')
    if not body_content:
        body_content = soup.find('div', class_='hidden-content')
    if body_content:
        desc = body_content.get_text(separator=' ', strip=True)
        if desc:
            metadata["description"] = desc
    # --- EMBED ---
    iframe = soup.find('iframe')
    if iframe and iframe.get('src'):
        embed_url = iframe['src'].strip()
        if embed_url.startswith('//'):
            embed_url = 'https:' + embed_url
        metadata["embed_url"] = embed_url
        parsed = urlparse(embed_url)
        metadata["embed_platform"] = parsed.netloc
    else:
        video = soup.find('video')
        if video:
            source = video.find('source')
            if source and source.get('src'):
                embed_url = source['src'].strip()
                if embed_url.startswith('//'):
                    embed_url = 'https:' + embed_url
                metadata["embed_url"] = embed_url
                parsed = urlparse(embed_url)
                metadata["embed_platform"] = parsed.netloc
        else:
            for a in soup.find_all('a', href=True):
                href = a['href']
                if any(x in href for x in ['dailymotion', 'youtube', 'ok.ru', 'vimeo']):
                    embed_url = href.strip()
                    if embed_url.startswith('//'):
                        embed_url = 'https:' + embed_url
                    metadata["embed_url"] = embed_url
                    parsed = urlparse(embed_url)
                    metadata["embed_platform"] = parsed.netloc
                    break
    return metadata

def parse_html_with_regex(html_content, url):
    metadata = {
        "url": url,
        "title": None,
        "season": None,
        "episode": None,
        "image": None,
        "description": None,
        "embed_url": None,
        "embed_platform": None
    }
    try:
        match = re.search(r'<meta\s+property="article:section"\s+content="([^"]+)"', html_content, re.IGNORECASE)
        if match:
            metadata["title"] = match.group(1).strip()
        else:
            match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html_content, re.IGNORECASE)
            if match:
                raw = match.group(1).strip()
                cleaned = re.sub(r'\s*第\d+話\s*', '', raw)
                cleaned = re.sub(r'\s*Season\s*\d+\s*', '', cleaned, flags=re.IGNORECASE)
                cleaned = re.sub(r'\s*[-|]\s*9tsu.*$', '', cleaned)
                cleaned = re.sub(r'\s*[-|]\s*[Dd]ailymotion.*$', '', cleaned)
                cleaned = re.sub(r'\s*[-|]\s*[Mm]iomio.*$', '', cleaned)
                cleaned = re.sub(r'\s*[-|]\s*[Yy]outube.*$', '', cleaned)
                metadata["title"] = cleaned.strip()
            else:
                match = re.search(r'<title>(.*?)</title>', html_content, re.IGNORECASE | re.DOTALL)
                if match:
                    raw = match.group(1).strip()
                    cleaned = re.sub(r'\s*第\d+話\s*', '', raw)
                    cleaned = re.sub(r'\s*Season\s*\d+\s*', '', cleaned, flags=re.IGNORECASE)
                    cleaned = re.sub(r'\s*[-|]\s*9tsu.*$', '', cleaned)
                    cleaned = re.sub(r'\s*[-|]\s*[Dd]ailymotion.*$', '', cleaned)
                    cleaned = re.sub(r'\s*[-|]\s*[Mm]iomio.*$', '', cleaned)
                    cleaned = re.sub(r'\s*[-|]\s*[Yy]outube.*$', '', cleaned)
                    metadata["title"] = cleaned.strip()
        match = re.search(r'Season\s*(\d+)\s*[　]?\s*第(\d+)話', html_content, re.IGNORECASE)
        if match:
            metadata["season"] = int(match.group(1))
            metadata["episode"] = int(match.group(2))
        else:
            match = re.search(r'第(\d+)話', html_content)
            if match:
                metadata["season"] = 1
                metadata["episode"] = int(match.group(1))
        match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html_content, re.IGNORECASE)
        if match:
            metadata["image"] = match.group(1).strip()
        match = re.search(r'<div\s+class="body-content[^"]*"[^>]*>(.*?)</div>', html_content, re.IGNORECASE | re.DOTALL)
        if match:
            desc = re.sub(r'<[^>]+>', '', match.group(1)).strip()
            if desc:
                metadata["description"] = desc
        else:
            match = re.search(r'<div\s+class="hidden-content[^"]*"[^>]*>(.*?)</div>', html_content, re.IGNORECASE | re.DOTALL)
            if match:
                desc = re.sub(r'<[^>]+>', '', match.group(1)).strip()
                if desc:
                    metadata["description"] = desc
        match = re.search(r'<iframe[^>]+src="([^"]+)"', html_content, re.IGNORECASE)
        if match:
            embed_url = match.group(1).strip()
            if embed_url.startswith('//'):
                embed_url = 'https:' + embed_url
            metadata["embed_url"] = embed_url
            parsed = urlparse(embed_url)
            metadata["embed_platform"] = parsed.netloc
        else:
            match = re.search(r'<video[^>]*>.*?<source[^>]+src="([^"]+)"', html_content, re.IGNORECASE | re.DOTALL)
            if match:
                embed_url = match.group(1).strip()
                if embed_url.startswith('//'):
                    embed_url = 'https:' + embed_url
                metadata["embed_url"] = embed_url
                parsed = urlparse(embed_url)
                metadata["embed_platform"] = parsed.netloc
            else:
                match = re.search(r'href="([^"]*(?:dailymotion|youtube|ok\.ru|vimeo)[^"]*)"', html_content, re.IGNORECASE)
                if match:
                    embed_url = match.group(1).strip()
                    if embed_url.startswith('//'):
                        embed_url = 'https:' + embed_url
                    metadata["embed_url"] = embed_url
                    parsed = urlparse(embed_url)
                    metadata["embed_platform"] = parsed.netloc
    except Exception as e:
        print(f"   ❌ Regex fallback error: {e}")
    return metadata

# ============================================================
# 7. FUNGSI UTAMA - DENGAN LOGIKA 500 DARI SEMUA SITEMAP
# ============================================================

def crawl_one_sitemap(force_download=False, reset=False, max_pages=None):
    init_database()
    
    if reset:
        reset_processing_state()
    
    # Auto reset jika semua sitemap selesai
    if is_all_sitemaps_processed():
        print("=" * 60)
        print("🔄 SEMUA SITEMAP SUDAH DIPROSES 100%")
        print("📡 Melakukan AUTO RESET dan download ulang semua sitemap...")
        print("=" * 60)
        reset_processing_state()
        download_all_sitemaps()
        # Set semua sitemap ke status pending
        for f in get_sitemap_files():
            all_urls = get_urls_from_local_sitemap(f)
            if all_urls:
                upsert_processing_state(f, 0, len(all_urls), 'pending')
        print("✅ Reset selesai. Memulai proses dari awal...")
        print("=" * 60)
    
    elif force_download:
        download_all_sitemaps()
        for f in get_sitemap_files():
            all_urls = get_urls_from_local_sitemap(f)
            if all_urls:
                upsert_processing_state(f, 0, len(all_urls), 'pending')
    
    # Pastikan sitemap tersedia
    sitemap_files = get_sitemap_files()
    if not sitemap_files:
        print("📂 Tidak ada sitemap lokal. Download semua...")
        download_all_sitemaps()
        for f in get_sitemap_files():
            all_urls = get_urls_from_local_sitemap(f)
            if all_urls:
                upsert_processing_state(f, 0, len(all_urls), 'pending')
    
    # Dapatkan daftar sitemap yang belum selesai (status pending/processing)
    unprocessed = get_unprocessed_sitemaps()
    if not unprocessed:
        print("✅ Semua sitemap sudah diproses. Selesai.")
        return
    
    # Kumpulkan URL baru dari semua sitemap hingga mencapai BATCH_SIZE
    target_count = BATCH_SIZE
    if max_pages and max_pages < target_count:
        target_count = max_pages
        print(f"🔢 Testing: target {target_count} link")
    
    all_new_urls = []          # List of (url, sitemap_file, offset, total)
    processed_sitemap_info = [] # Untuk update state nanti
    
    remaining = target_count
    for sitemap_file, offset, total in unprocessed:
        if remaining <= 0:
            break
        # Ambil batch dari sitemap ini
        batch, new_offset, total_urls = get_url_batch_from_sitemap(sitemap_file, offset, remaining)
        if not batch:
            # Tidak ada URL baru di sitemap ini, tandai selesai
            mark_sitemap_processed(sitemap_file)
            continue
        # Filter URL yang sudah ada di database
        existing, new_urls = get_existing_urls(batch)
        if not new_urls:
            # Semua URL di batch ini sudah ada, update offset ke new_offset
            if new_offset >= total_urls:
                mark_sitemap_processed(sitemap_file)
            else:
                upsert_processing_state(sitemap_file, new_offset, total_urls, 'pending')
            continue
        # Simpan URL baru dengan info sitemap
        for url in new_urls:
            all_new_urls.append((url, sitemap_file))
        # Update sisa kuota
        remaining -= len(new_urls)
        # Simpan informasi untuk update state nanti
        processed_sitemap_info.append({
            'sitemap_file': sitemap_file,
            'new_offset': new_offset,
            'total': total_urls,
            'taken': len(new_urls)
        })
    
    if not all_new_urls:
        print("✅ Tidak ada URL baru ditemukan di semua sitemap.")
        # Tandai semua sitemap yang sudah habis sebagai done
        for sitemap_file, offset, total in unprocessed:
            if offset >= total:
                mark_sitemap_processed(sitemap_file)
        return
    
    print(f"📌 Mengumpulkan {len(all_new_urls)} URL baru dari {len(set(s for _, s in all_new_urls))} sitemap")
    
    # Proses setiap URL baru
    results = []
    for i, (url, sitemap_file) in enumerate(all_new_urls, 1):
        print(f"\n🔄 [{i}/{len(all_new_urls)}] {url} (dari {sitemap_file})")
        print("-" * 60)
        html_content, status = download_html_page(url)
        if status == 200 and html_content:
            print(f"   ✅ HTML berhasil di-download ({len(html_content)} bytes)")
            metadata = parse_html_page(html_content, url)
            print(f"   📝 Hasil parsing:")
            print(f"      - Title: {metadata['title']}")
            print(f"      - Season: {metadata['season']}")
            print(f"      - Episode: {metadata['episode']}")
            print(f"      - Embed Platform: {metadata['embed_platform']}")
            print(f"      - Embed URL: {metadata['embed_url']}")
            if metadata['description']:
                desc_preview = metadata['description'][:100] + '...' if len(metadata['description']) > 100 else metadata['description']
                print(f"      - Description: {desc_preview}")
            else:
                print(f"      - Description: None")
            results.append(metadata)
        else:
            print(f"   ❌ Gagal download (status {status})")
            metadata = {
                "url": url,
                "title": None,
                "season": None,
                "episode": None,
                "image": None,
                "description": None,
                "embed_url": None,
                "embed_platform": None,
                "error": f"HTTP {status}"
            }
            results.append(metadata)
        time.sleep(1)
    
    new_count = save_to_database(results)
    print(f"\n💾 Database: {new_count} link baru ditambahkan")
    
    # Update state setiap sitemap yang sudah diambil
    for info in processed_sitemap_info:
        sitemap_file = info['sitemap_file']
        new_offset = info['new_offset']
        total = info['total']
        if new_offset >= total:
            mark_sitemap_processed(sitemap_file)
            print(f"✅ Sitemap {sitemap_file} selesai ({total} link)")
        else:
            upsert_processing_state(sitemap_file, new_offset, total, 'pending')
            print(f"📌 Progress {sitemap_file}: {new_offset}/{total} link diproses")
    
    export_to_json()
    total_db = get_database_count()
    print(f"\n📊 Total link di database: {total_db}")

# ============================================================
# 8. EKSEKUSI
# ============================================================

if __name__ == "__main__":
    import sys
    force_download = False
    reset = False
    max_pages = None
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i].lower()
        if arg == '--download':
            force_download = True
            print("🔧 Mode: Download ulang semua sitemap")
        elif arg == '--reset':
            reset = True
            print("🔧 Mode: Reset semua status pemrosesan")
        elif arg == '--max-pages' and i + 1 < len(sys.argv):
            try:
                max_pages = int(sys.argv[i + 1])
                print(f"🔧 Mode testing: hanya {max_pages} link")
                i += 1
            except ValueError:
                print(f"⚠️ Argumen --max-pages harus berupa angka")
        else:
            print(f"⚠️ Argumen tidak dikenal: {sys.argv[i]}")
            print("Gunakan --download, --reset, atau --max-pages N")
        i += 1
    print("=" * 60)
    print("🚀 PENGEPUL-LINK - Crawler 9tsu.in (500 dari semua sitemap)")
    print(f"📌 Target: {BATCH_SIZE} link per run dari seluruh sitemap")
    if max_pages:
        print(f"🔢 Max pages: {max_pages}")
    print("=" * 60)
    crawl_one_sitemap(force_download, reset, max_pages)
