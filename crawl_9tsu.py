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

ALTERNATIVE_DOMAINS = ["https://9tsu.vip", "https://9tsu.cc"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "identity",  # 🔥 Kunci: tolak kompresi
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
    
    conn.commit()
    conn.close()
    print("✅ Database siap")

def is_url_exists(url):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM links WHERE url = ?", (url,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def save_to_database(metadata_list):
    if not metadata_list:
        return 0
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    new_count = 0
    for data in metadata_list:
        if not is_url_exists(data.get('url')):
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
    
    output = {
        'timestamp': datetime.now().isoformat(),
        'total': len(links),
        'links': links
    }
    
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
# 3. FUNGSI STATUS SITEMAP
# ============================================================

def mark_sitemap_processed(sitemap_file):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO processed_sitemaps (sitemap_file) VALUES (?)', (sitemap_file,))
    conn.commit()
    conn.close()

def get_processed_sitemaps():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT sitemap_file FROM processed_sitemaps')
    rows = cursor.fetchall()
    conn.close()
    return {row[0] for row in rows}

# ============================================================
# 4. MANAJEMEN SITEMAP LOKAL
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

def download_all_sitemaps():
    create_sitemap_dir()
    
    index_content, used_domain = get_sitemap_index_content()
    if index_content is None:
        print("❌ Gagal mengakses sitemap index dari semua domain.")
        return
    
    try:
        root = ET.fromstring(index_content)
        ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        sitemap_urls = []
        for loc in root.findall('.//ns:loc', ns):
            url = loc.text
            if url and 'post-sitemap' in url.lower():
                sitemap_urls.append(url)
        print(f"✅ Ditemukan {len(sitemap_urls)} post-sitemap dari {used_domain}")
    except Exception as e:
        print(f"❌ Error parsing sitemap index: {e}")
        return
    
    for idx, url in enumerate(sitemap_urls, 1):
        filename = url.split('/')[-1]
        filepath = os.path.join(SITEMAP_DIR, filename)
        
        if os.path.exists(filepath):
            print(f"⏭️  {filename} sudah ada, dilewati")
            continue
        
        print(f"⬇️  Download {filename} ({idx}/{len(sitemap_urls)})")
        content, status = download_sitemap_with_cloudscraper(url)
        
        if status == 200 and content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"   ✅ Tersimpan: {filepath}")
        else:
            print(f"   ❌ Gagal download (status {status})")
            for alt_domain in ALTERNATIVE_DOMAINS:
                alt_url = url.replace(BASE_URL, alt_domain)
                print(f"   🔄 Mencoba alternatif: {alt_url}")
                content2, status2 = download_sitemap_with_cloudscraper(alt_url)
                if status2 == 200 and content2:
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(content2)
                    print(f"   ✅ Tersimpan dari alternatif: {filepath}")
                    break
                else:
                    print(f"   ❌ Gagal alternatif (status {status2})")
        
        time.sleep(0.5)
    
    print("✅ Semua sitemap selesai diunduh")

def get_sitemap_files():
    create_sitemap_dir()
    files = [f for f in os.listdir(SITEMAP_DIR) if f.startswith('post-sitemap') and f.endswith('.xml')]
    if not files:
        return []
    files.sort(key=lambda x: int(re.search(r'(\d+)', x).group(1)) if re.search(r'(\d+)', x) else 0)
    return files

def get_next_unprocessed_sitemap():
    all_files = get_sitemap_files()
    if not all_files:
        return None
    processed = get_processed_sitemaps()
    for f in all_files:
        if f not in processed:
            return f
    return None

def get_urls_from_local_sitemap(sitemap_filename):
    filepath = os.path.join(SITEMAP_DIR, sitemap_filename)
    if not os.path.exists(filepath):
        print(f"❌ File tidak ditemukan: {filepath}")
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

# ============================================================
# 🔥 5. DOWNLOAD HTML - FIX BINARY
# ============================================================

def download_html_with_cloudscraper(url):
    """Download HTML dengan cloudscraper dan identity encoding"""
    try:
        scraper = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
            delay=True,
            interpreter='native'
        )
        scraper.headers.update(HEADERS)
        response = scraper.get(url, timeout=60)
        
        if response.status_code == 200:
            # Coba dapatkan raw content
            raw = response.content
            
            # Cek apakah gzip
            if len(raw) >= 2 and raw[0] == 0x1F and raw[1] == 0x8B:
                try:
                    raw = gzip.decompress(raw)
                    print("   🔓 Decompressed gzip")
                except:
                    pass
            
            # Decode dengan UTF-8
            try:
                html = raw.decode('utf-8')
            except:
                html = raw.decode('latin-1', errors='ignore')
            
            # Cek apakah HTML valid
            if html and len(html) > 100 and any(tag in html[:200] for tag in ['<html', '<!DOCTYPE', '<title', '<body']):
                return html, 200
            else:
                # Coba response.text sebagai alternatif
                try:
                    response.encoding = 'utf-8'
                    html2 = response.text
                    if html2 and len(html2) > 100 and any(tag in html2[:200] for tag in ['<html', '<!DOCTYPE', '<title', '<body']):
                        return html2, 200
                except:
                    pass
                print(f"   ⚠️ Konten tidak valid (binary atau challenge)")
                return None, 403
        else:
            return None, response.status_code
    except Exception as e:
        print(f"   ❌ Cloudscraper error: {e}")
        return None, 0

def download_html_with_curl(url):
    """Fallback: download dengan curl"""
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
            # Cek gzip
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
    """
    Download HTML dengan multiple metode:
    1. Cloudscraper (identity encoding)
    2. Curl fallback
    """
    # Metode 1: Cloudscraper
    for attempt in range(retry):
        print(f"   📡 Attempt {attempt+1}/{retry} with cloudscraper...")
        html, status = download_html_with_cloudscraper(url)
        if status == 200 and html:
            return html, 200
        if status == 403 and 'Just a moment' in str(html):
            print(f"   ⚠️ Cloudflare challenge detected, retrying...")
            time.sleep(3 + attempt * 2)
            continue
        if status != 403:
            break
    
    # Metode 2: Curl fallback
    print("   🔄 Curl fallback...")
    html, status = download_html_with_curl(url)
    if status == 200 and html:
        return html, 200
    
    return None, 403

# ============================================================
# 6. PARSING HTML (Sama seperti sebelumnya)
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
        metadata["embed_url"] = embed_url
        parsed = urlparse(embed_url)
        metadata["embed_platform"] = parsed.netloc
    else:
        video = soup.find('video')
        if video:
            source = video.find('source')
            if source and source.get('src'):
                embed_url = source['src'].strip()
                metadata["embed_url"] = embed_url
                parsed = urlparse(embed_url)
                metadata["embed_platform"] = parsed.netloc
    
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
            metadata["embed_url"] = embed_url
            parsed = urlparse(embed_url)
            metadata["embed_platform"] = parsed.netloc
        else:
            match = re.search(r'<video[^>]*>.*?<source[^>]+src="([^"]+)"', html_content, re.IGNORECASE | re.DOTALL)
            if match:
                embed_url = match.group(1).strip()
                metadata["embed_url"] = embed_url
                parsed = urlparse(embed_url)
                metadata["embed_platform"] = parsed.netloc
    
    except Exception as e:
        print(f"   ❌ Regex fallback error: {e}")
    
    return metadata

# ============================================================
# 7. FUNGSI UTAMA
# ============================================================

def crawl_one_sitemap(force_download=False):
    init_database()
    
    sitemap_files = get_sitemap_files()
    
    if force_download or not sitemap_files:
        download_all_sitemaps()
        sitemap_files = get_sitemap_files()
    else:
        print(f"📂 Menggunakan {len(sitemap_files)} sitemap lokal yang sudah ada")
    
    next_sitemap = get_next_unprocessed_sitemap()
    if not next_sitemap:
        print("✅ Semua sitemap sudah diproses. Tidak ada yang baru.")
        return
    
    print(f"📌 Memproses sitemap: {next_sitemap}")
    
    urls = get_urls_from_local_sitemap(next_sitemap)
    if not urls:
        print(f"❌ Tidak ada URL ditemukan di {next_sitemap}")
        mark_sitemap_processed(next_sitemap)
        return
    
    print(f"✅ Total URL dalam sitemap: {len(urls)}")
    
    new_urls = [url for url in urls if not is_url_exists(url)]
    print(f"🆕 URL baru: {len(new_urls)}")
    
    if not new_urls:
        print("✅ Tidak ada konten baru di sitemap ini.")
        mark_sitemap_processed(next_sitemap)
        return
    
    results = []
    for i, url in enumerate(new_urls, 1):
        print(f"\n🔄 [{i}/{len(new_urls)}] {url}")
        print("-" * 60)
        
        html_content, status = download_html_page(url)
        
        if status == 200 and html_content:
            print(f"   ✅ HTML berhasil di-download ({len(html_content)} bytes)")
            
            preview = html_content[:100].replace('\n', ' ').replace('\r', ' ')
            print(f"   🔍 Preview: {preview}...")
            
            metadata = parse_html_page(html_content, url)
            print(f"   📝 Hasil parsing:")
            print(f"      - Title: {metadata['title']}")
            print(f"      - Season: {metadata['season']}")
            print(f"      - Episode: {metadata['episode']}")
            print(f"      - Embed Platform: {metadata['embed_platform']}")
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
    
    mark_sitemap_processed(next_sitemap)
    print(f"✅ Sitemap {next_sitemap} ditandai sudah diproses")
    
    export_to_json()
    
    total = get_database_count()
    print(f"\n📊 Total link di database: {total}")

# ============================================================
# 8. EKSEKUSI
# ============================================================

if __name__ == "__main__":
    import sys
    
    force_download = False
    if len(sys.argv) > 1:
        if sys.argv[1].lower() == '--download':
            force_download = True
            print("🔧 Mode: Download ulang semua sitemap")
        else:
            print("⚠️ Argumen tidak dikenal. Gunakan --download untuk mengunduh sitemap.")
    
    print("=" * 60)
    print("🚀 PENGEPUL-LINK - Crawler 9tsu.in")
    print("📌 Mode: 1 sitemap terbaru per siklus (Binary Fixed)")
    print("=" * 60)
    
    crawl_one_sitemap(force_download)
