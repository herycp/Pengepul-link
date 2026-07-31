import cloudscraper
import xml.etree.ElementTree as ET
import json
import re
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse

# ============================================================
# 1. KONFIGURASI
# ============================================================

BASE_URL = "https://9tsu.in"
SITEMAP_INDEX = f"{BASE_URL}/sitemap_index.xml"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
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
# 2. PARSING TITLE, SEASON, EPISODE
# ============================================================

def parse_title_season_episode(original_title):
    """Parsing judul untuk mendapatkan title, season, episode"""
    if not original_title:
        return None, None, None

    title = original_title.strip()
    season = None
    episode = None

    # Pola 1: "Judul Season11　第10話"
    pattern1 = r'^(.+?)\s+Season(\d+)\s*[　]?\s*第(\d+)話'
    match = re.search(pattern1, original_title, re.IGNORECASE)
    if match:
        title = match.group(1).strip()
        season = int(match.group(2))
        episode = int(match.group(3))
        return title, season, episode

    # Pola 2: "Judul 第5話" -> season = 1
    pattern2 = r'^(.+?)\s*[　]?\s*第(\d+)話'
    match = re.search(pattern2, original_title)
    if match:
        title = match.group(1).strip()
        episode = int(match.group(2))
        season = 1
        return title, season, episode

    # Pola 3: "Judul S02E05"
    pattern3 = r'^(.+?)\s+[sS](\d+)[eE](\d+)'
    match = re.search(pattern3, original_title)
    if match:
        title = match.group(1).strip()
        season = int(match.group(2))
        episode = int(match.group(3))
        return title, season, episode

    return title, None, None


# ============================================================
# 3. EKSTRAKSI TITLE DARI HTML (DENGAN DEBUG)
# ============================================================

def extract_title_from_html(html_content, url):
    """
    Mencoba berbagai cara untuk mengekstrak judul dari HTML
    """
    methods = []
    
    # 1. Dari <title>
    match = re.search(r'<title>(.*?)</title>', html_content, re.IGNORECASE | re.DOTALL)
    if match:
        raw = match.group(1).strip()
        raw = re.sub(r'\s*[-|]\s*9tsu.*$', '', raw).strip()
        raw = re.sub(r'\s*[-|]\s*[Dd]ailymotion.*$', '', raw).strip()
        raw = re.sub(r'\s*[-|]\s*[Mm]iomio.*$', '', raw).strip()
        if raw:
            return raw
    
    # 2. Dari <h1> atau <h2> dengan class tertentu
    match = re.search(r'<h1[^>]*>(.*?)</h1>', html_content, re.IGNORECASE | re.DOTALL)
    if match:
        raw = re.sub(r'<[^>]+>', '', match.group(1)).strip()
        if raw:
            return raw
    
    # 3. Dari meta property="og:title"
    match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html_content, re.IGNORECASE)
    if match:
        raw = match.group(1).strip()
        if raw:
            return raw
    
    # 4. Dari meta name="title"
    match = re.search(r'<meta\s+name="title"\s+content="([^"]+)"', html_content, re.IGNORECASE)
    if match:
        raw = match.group(1).strip()
        if raw:
            return raw
    
    # 5. Dari class "entry-title" (umum di WordPress)
    match = re.search(r'<[^>]+class="[^"]*entry-title[^"]*"[^>]*>(.*?)</', html_content, re.IGNORECASE | re.DOTALL)
    if match:
        raw = re.sub(r'<[^>]+>', '', match.group(1)).strip()
        if raw:
            return raw
    
    # 6. Dari schema.org itemprop="name"
    match = re.search(r'<[^>]+itemprop="name"[^>]*>(.*?)</', html_content, re.IGNORECASE | re.DOTALL)
    if match:
        raw = re.sub(r'<[^>]+>', '', match.group(1)).strip()
        if raw:
            return raw
    
    # Jika semua gagal, gunakan nama file dari URL
    path = urlparse(url).path
    filename = path.split('/')[-1].replace('.html', '')
    if filename:
        return filename
    
    return None


# ============================================================
# 4. AMBIL URL DARI SITEMAP (HANYA POST-SITEMAP)
# ============================================================

def get_all_article_urls():
    """
    Ambil semua URL artikel dari sitemap_index.xml
    HANYA dari post-sitemap (bukan page-sitemap, category-sitemap, dll)
    """
    try:
        print(f"📡 Mengambil daftar sitemap dari: {SITEMAP_INDEX}")
        
        scraper = cloudscraper.create_scraper()
        scraper.headers.update(HEADERS)
        
        response = scraper.get(SITEMAP_INDEX, timeout=60)
        response.raise_for_status()
        
        root = ET.fromstring(response.content)
        ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        
        all_urls = []
        for loc in root.findall('.//ns:loc', ns):
            sitemap_url = loc.text
            if sitemap_url:
                # 🔥 FILTER: HANYA yang mengandung "post-sitemap"
                if 'post-sitemap' in sitemap_url.lower():
                    print(f"   ✅ Memproses: {sitemap_url}")
                    urls = extract_urls_from_sitemap(sitemap_url)
                    all_urls.extend(urls)
                    print(f"      → {len(urls)} URL ditemukan")
                else:
                    print(f"   ⏭️  Skip: {sitemap_url}")
                time.sleep(0.5)
        
        print(f"✅ Total URL ditemukan: {len(all_urls)}")
        return all_urls
    except Exception as e:
        print(f"❌ Error fetching sitemap: {e}")
        return []


def extract_urls_from_sitemap(sitemap_url):
    """
    Ekstrak URL dari satu file sitemap
    """
    try:
        scraper = cloudscraper.create_scraper()
        scraper.headers.update(HEADERS)
        
        response = scraper.get(sitemap_url, timeout=60)
        response.raise_for_status()
        
        root = ET.fromstring(response.content)
        ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        
        urls = []
        for loc in root.findall('.//ns:loc', ns):
            url = loc.text
            if url:
                # Hanya URL artikel (.html atau /drama/)
                if url.endswith('.html') or '/drama/' in url:
                    urls.append(url)
        return urls
    except Exception as e:
        print(f"⚠️ Error parsing sitemap {sitemap_url}: {e}")
        return []


# ============================================================
# 5. EKSTRAK METADATA DENGAN TITLE BARU
# ============================================================

def extract_metadata(url, html_content):
    """
    Ekstrak metadata dari halaman artikel
    """
    metadata = {
        "url": url,
        "title": None,
        "original_title": None,
        "season": None,
        "episode": None,
        "image": None,
        "source_page": BASE_URL
    }
    
    # Ekstrak title
    raw_title = extract_title_from_html(html_content, url)
    
    if raw_title:
        # Hapus angka di awal jika ada (misal "125645.html")
        raw_title = re.sub(r'^\d+\.?html?\s*[-|]?\s*', '', raw_title)
        metadata["original_title"] = raw_title
        title, season, episode = parse_title_season_episode(raw_title)
        metadata["title"] = title or raw_title
        metadata["season"] = season
        metadata["episode"] = episode
    else:
        # Fallback ke URL
        path = urlparse(url).path
        fallback = path.split('/')[-1].replace('.html', '')
        metadata["title"] = fallback
        metadata["original_title"] = fallback
    
    # Ambil gambar
    img_match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html_content, re.IGNORECASE)
    if img_match:
        metadata["image"] = img_match.group(1)
    
    return metadata


# ============================================================
# 6. FUNGSI UTAMA CRAWL
# ============================================================

def crawl_and_index(max_pages=None):
    """Fungsi utama crawling dan indexing"""
    
    urls = get_all_article_urls()
    
    if not urls:
        print("⚠️ Gagal mengambil URL dari sitemap.")
        return None
    
    if max_pages:
        urls = urls[:max_pages]
        print(f"🔧 Mode testing: hanya {max_pages} dari {len(urls)} URL")
    
    print(f"✅ Memproses {len(urls)} URL artikel")
    
    results = []
    scraper = cloudscraper.create_scraper()
    scraper.headers.update(HEADERS)
    
    for i, url in enumerate(urls):
        try:
            print(f"🔄 [{i+1}/{len(urls)}]: {url}")
            
            response = scraper.get(url, timeout=60)
            
            if response.status_code == 200:
                metadata = extract_metadata(url, response.text)
                results.append(metadata)
                print(f"   ✅ Title: {metadata['title']} (S{metadata['season']} E{metadata['episode']})")
            else:
                print(f"   ❌ Status: {response.status_code}")
            
            time.sleep(1)
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
    
    # Simpan ke file
    output = {
        "timestamp": datetime.now().isoformat(),
        "total": len(results),
        "links": results
    }
    
    with open("links.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Selesai! {len(results)} link berhasil di-index")
    print(f"📁 File disimpan sebagai: links.json")
    
    return output


# ============================================================
# 7. EKSEKUSI
# ============================================================

if __name__ == "__main__":
    import sys
    
    max_pages = None
    if len(sys.argv) > 1:
        try:
            max_pages = int(sys.argv[1])
        except ValueError:
            print("⚠️ Argumen harus berupa angka")
    
    print("=" * 50)
    print("🚀 PENGEPUL-LINK - Crawler 9tsu.in (Post-Sitemap Only)")
    print("=" * 50)
    
    crawl_and_index(max_pages)
