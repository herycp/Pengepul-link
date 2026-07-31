import cloudscraper
import xml.etree.ElementTree as ET
import json
import re
import time
from datetime import datetime
from urllib.parse import urlparse

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
# 2. EKSTRAKSI SEASON & EPISODE DARI HTML
# ============================================================

def extract_season_episode(html_content):
    """
    Ekstrak season dan episode dari konten HTML
    """
    season = None
    episode = None
    
    # Pola 1: "Season11　第10話" atau "Season 11 第10話"
    pattern1 = r'Season\s*(\d+)\s*[　]?\s*第(\d+)話'
    match = re.search(pattern1, html_content, re.IGNORECASE)
    if match:
        return int(match.group(1)), int(match.group(2))
    
    # Pola 2: "第3話" (hanya episode) -> season default = 1
    pattern2 = r'第(\d+)話'
    match = re.search(pattern2, html_content)
    if match:
        return 1, int(match.group(1))
    
    # Pola 3: "S02E05" atau "S2E5"
    pattern3 = r'[sS](\d+)[eE](\d+)'
    match = re.search(pattern3, html_content)
    if match:
        return int(match.group(1)), int(match.group(2))
    
    return season, episode


# ============================================================
# 3. EKSTRAKSI TITLE BERSIH DARI HTML
# ============================================================

def extract_cleaned_title(html_content):
    """
    Ekstrak title bersih (tanpa season/episode/nama situs)
    Prioritas: article:section > og:title > title
    """
    
    # 1. Coba dari article:section (paling bersih)
    match = re.search(r'<meta\s+property="article:section"\s+content="([^"]+)"', html_content, re.IGNORECASE)
    if match:
        title = match.group(1).strip()
        if title:
            return title
    
    # 2. Coba dari og:title
    match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html_content, re.IGNORECASE)
    if match:
        title = match.group(1).strip()
        # Bersihkan dari teks tambahan
        title = re.sub(r'\s*第\d+話\s*', '', title)
        title = re.sub(r'\s*Season\s*\d+\s*', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s*[-|]\s*9tsu.*$', '', title)
        title = re.sub(r'\s*[-|]\s*[Dd]ailymotion.*$', '', title)
        title = re.sub(r'\s*[-|]\s*[Mm]iomio.*$', '', title)
        title = re.sub(r'\s*[-|]\s*[Yy]outube.*$', '', title)
        title = title.strip()
        if title:
            return title
    
    # 3. Coba dari <title>
    match = re.search(r'<title>(.*?)</title>', html_content, re.IGNORECASE | re.DOTALL)
    if match:
        title = match.group(1).strip()
        title = re.sub(r'\s*第\d+話\s*', '', title)
        title = re.sub(r'\s*Season\s*\d+\s*', '', title, flags=re.IGNORECASE)
        title = re.sub(r'\s*[-|]\s*9tsu.*$', '', title)
        title = re.sub(r'\s*[-|]\s*[Dd]ailymotion.*$', '', title)
        title = re.sub(r'\s*[-|]\s*[Mm]iomio.*$', '', title)
        title = re.sub(r'\s*[-|]\s*[Yy]outube.*$', '', title)
        title = title.strip()
        if title:
            return title
    
    return None


# ============================================================
# 4. EKSTRAKSI ORIGINAL TITLE (MENTAH)
# ============================================================

def extract_original_title(html_content):
    """
    Ekstrak original title (mentah dari halaman)
    """
    # Coba dari og:title
    match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html_content, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    
    # Coba dari <title>
    match = re.search(r'<title>(.*?)</title>', html_content, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    
    return None


# ============================================================
# 5. EKSTRAKSI IMAGE
# ============================================================

def extract_image(html_content):
    """
    Ekstrak URL gambar dari meta og:image
    """
    match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html_content, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


# ============================================================
# 6. EKSTRAKSI METADATA LENGKAP
# ============================================================

def extract_metadata(url, html_content):
    """
    Ekstrak semua metadata dari halaman
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
    
    # Original title
    metadata["original_title"] = extract_original_title(html_content)
    
    # Title bersih
    metadata["title"] = extract_cleaned_title(html_content)
    
    # Jika title masih None, gunakan original_title yang sudah dibersihkan
    if not metadata["title"] and metadata["original_title"]:
        metadata["title"] = metadata["original_title"]
        metadata["title"] = re.sub(r'\s*第\d+話\s*', '', metadata["title"])
        metadata["title"] = re.sub(r'\s*Season\s*\d+\s*', '', metadata["title"], flags=re.IGNORECASE)
        metadata["title"] = re.sub(r'\s*[-|]\s*9tsu.*$', '', metadata["title"])
        metadata["title"] = re.sub(r'\s*[-|]\s*[Dd]ailymotion.*$', '', metadata["title"])
        metadata["title"] = re.sub(r'\s*[-|]\s*[Mm]iomio.*$', '', metadata["title"])
        metadata["title"] = re.sub(r'\s*[-|]\s*[Yy]outube.*$', '', metadata["title"])
        metadata["title"] = metadata["title"].strip()
    
    # Season & Episode
    season, episode = extract_season_episode(html_content)
    metadata["season"] = season
    metadata["episode"] = episode
    
    # Image
    metadata["image"] = extract_image(html_content)
    
    return metadata


# ============================================================
# 7. AMBIL URL DARI SITEMAP (HANYA POST-SITEMAP)
# ============================================================

def get_all_article_urls():
    """
    Ambil semua URL artikel dari sitemap_index.xml
    HANYA dari post-sitemap (bukan page-sitemap, category-sitemap, dll)
    """
    try:
        print(f"📡 Mengambil sitemap index: {SITEMAP_INDEX}")
        
        scraper = cloudscraper.create_scraper()
        scraper.headers.update(HEADERS)
        
        response = scraper.get(SITEMAP_INDEX, timeout=60)
        response.raise_for_status()
        
        root = ET.fromstring(response.content)
        ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        
        all_urls = []
        for loc in root.findall('.//ns:loc', ns):
            sitemap_url = loc.text
            if sitemap_url and 'post-sitemap' in sitemap_url.lower():
                print(f"   ✅ Memproses: {sitemap_url}")
                urls = extract_urls_from_sitemap(sitemap_url)
                all_urls.extend(urls)
                print(f"      → {len(urls)} URL ditemukan")
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
            if url and (url.endswith('.html') or '/drama/' in url):
                urls.append(url)
        return urls
    except Exception as e:
        print(f"⚠️ Error parsing sitemap {sitemap_url}: {e}")
        return []


# ============================================================
# 8. FUNGSI UTAMA CRAWL & INDEX
# ============================================================

def crawl_and_index(max_pages=None):
    """
    Fungsi utama crawling dan indexing
    max_pages: batas maksimum halaman (untuk testing)
    """
    urls = get_all_article_urls()
    
    if not urls:
        print("❌ Tidak ada URL ditemukan.")
        return None
    
    if max_pages:
        urls = urls[:max_pages]
        print(f"🔧 Mode testing: hanya {max_pages} dari {len(urls)} URL")
    else:
        print(f"📊 Total URL akan diproses: {len(urls)}")
    
    results = []
    scraper = cloudscraper.create_scraper()
    scraper.headers.update(HEADERS)
    
    for i, url in enumerate(urls):
        try:
            print(f"🔄 [{i+1}/{len(urls)}] {url}")
            
            response = scraper.get(url, timeout=60)
            
            if response.status_code == 200:
                metadata = extract_metadata(url, response.text)
                results.append(metadata)
                print(f"   ✅ Title: {metadata['title']}")
                print(f"      Season: {metadata['season']}, Episode: {metadata['episode']}")
            else:
                print(f"   ❌ Status: {response.status_code}")
            
            # Jeda antar request
            time.sleep(1)
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
    
    # Buat output JSON
    output = {
        "timestamp": datetime.now().isoformat(),
        "total": len(results),
        "links": results
    }
    
    # Simpan ke file
    with open("links.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Selesai! {len(results)} link berhasil di-index")
    print(f"📁 File disimpan sebagai: links.json")
    
    return output


# ============================================================
# 9. EKSEKUSI
# ============================================================

if __name__ == "__main__":
    import sys
    
    max_pages = None
    if len(sys.argv) > 1:
        try:
            max_pages = int(sys.argv[1])
            print(f"🔧 Argumen: hanya {max_pages} halaman")
        except ValueError:
            print("⚠️ Argumen harus berupa angka. Menggunakan semua halaman.")
    
    print("=" * 50)
    print("🚀 PENGEPUL-LINK - Crawler & Scraper 9tsu.in")
    print("=" * 50)
    
    crawl_and_index(max_pages)
