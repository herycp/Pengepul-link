import cloudscraper
import xml.etree.ElementTree as ET
import json
import re
import time
from datetime import datetime
from urllib.parse import urlparse
from bs4 import BeautifulSoup

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
# 2. EKSTRAKSI METADATA DENGAN BEAUTIFULSOUP
# ============================================================

def extract_metadata_with_bs4(url, html_content, save_debug=False):
    """
    Ekstrak metadata menggunakan BeautifulSoup
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
    
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # --- 1. ORIGINAL TITLE ---
    # Coba dari meta property="og:title"
    og_title = soup.find('meta', property='og:title')
    if og_title and og_title.get('content'):
        metadata["original_title"] = og_title['content'].strip()
    else:
        # Coba dari <title>
        title_tag = soup.find('title')
        if title_tag:
            metadata["original_title"] = title_tag.get_text(strip=True)
    
    # --- 2. TITLE BERSIH ---
    # Prioritas: article:section > og:title > h1 > title
    cleaned_title = None
    
    # 2a. Coba dari meta property="article:section"
    article_section = soup.find('meta', property='article:section')
    if article_section and article_section.get('content'):
        cleaned_title = article_section['content'].strip()
    
    # 2b. Jika tidak ada, coba dari og:title
    if not cleaned_title and og_title and og_title.get('content'):
        cleaned_title = og_title['content'].strip()
        # Bersihkan
        cleaned_title = re.sub(r'\s*第\d+話\s*', '', cleaned_title)
        cleaned_title = re.sub(r'\s*Season\s*\d+\s*', '', cleaned_title, flags=re.IGNORECASE)
        cleaned_title = re.sub(r'\s*[-|]\s*9tsu.*$', '', cleaned_title)
        cleaned_title = re.sub(r'\s*[-|]\s*[Dd]ailymotion.*$', '', cleaned_title)
        cleaned_title = re.sub(r'\s*[-|]\s*[Mm]iomio.*$', '', cleaned_title)
        cleaned_title = re.sub(r'\s*[-|]\s*[Yy]outube.*$', '', cleaned_title)
        cleaned_title = cleaned_title.strip()
    
    # 2c. Coba dari <h1>
    if not cleaned_title:
        h1 = soup.find('h1')
        if h1:
            cleaned_title = h1.get_text(strip=True)
            cleaned_title = re.sub(r'\s*第\d+話\s*', '', cleaned_title)
            cleaned_title = re.sub(r'\s*Season\s*\d+\s*', '', cleaned_title, flags=re.IGNORECASE)
            cleaned_title = cleaned_title.strip()
    
    # 2d. Coba dari <title> (fallback)
    if not cleaned_title:
        title_tag = soup.find('title')
        if title_tag:
            cleaned_title = title_tag.get_text(strip=True)
            cleaned_title = re.sub(r'\s*第\d+話\s*', '', cleaned_title)
            cleaned_title = re.sub(r'\s*Season\s*\d+\s*', '', cleaned_title, flags=re.IGNORECASE)
            cleaned_title = re.sub(r'\s*[-|]\s*9tsu.*$', '', cleaned_title)
            cleaned_title = re.sub(r'\s*[-|]\s*[Dd]ailymotion.*$', '', cleaned_title)
            cleaned_title = re.sub(r'\s*[-|]\s*[Mm]iomio.*$', '', cleaned_title)
            cleaned_title = re.sub(r'\s*[-|]\s*[Yy]outube.*$', '', cleaned_title)
            cleaned_title = cleaned_title.strip()
    
    metadata["title"] = cleaned_title
    
    # --- 3. SEASON & EPISODE ---
    # Cari di seluruh teks HTML
    html_text = soup.get_text()
    
    # Pola 1: "Season11　第10話"
    pattern1 = r'Season\s*(\d+)\s*[　]?\s*第(\d+)話'
    match = re.search(pattern1, html_text, re.IGNORECASE)
    if match:
        metadata["season"] = int(match.group(1))
        metadata["episode"] = int(match.group(2))
    else:
        # Pola 2: "第3話" -> season = 1
        pattern2 = r'第(\d+)話'
        match = re.search(pattern2, html_text)
        if match:
            metadata["season"] = 1
            metadata["episode"] = int(match.group(1))
        else:
            # Pola 3: "S02E05"
            pattern3 = r'[sS](\d+)[eE](\d+)'
            match = re.search(pattern3, html_text)
            if match:
                metadata["season"] = int(match.group(1))
                metadata["episode"] = int(match.group(2))
    
    # --- 4. IMAGE ---
    og_image = soup.find('meta', property='og:image')
    if og_image and og_image.get('content'):
        metadata["image"] = og_image['content'].strip()
    
    # --- DEBUG: Simpan HTML sampel jika diminta ---
    if save_debug:
        debug_filename = f"debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        with open(debug_filename, 'w', encoding='utf-8') as f:
            f.write(html_content)
        print(f"   📄 Debug HTML disimpan: {debug_filename}")
    
    return metadata


# ============================================================
# 3. AMBIL URL DARI SITEMAP (HANYA POST-SITEMAP)
# ============================================================

def get_all_article_urls():
    """
    Ambil semua URL artikel dari sitemap_index.xml
    HANYA dari post-sitemap
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
# 4. FUNGSI UTAMA CRAWL & INDEX
# ============================================================

def crawl_and_index(max_pages=None, save_debug_first=False):
    """
    Fungsi utama crawling dan indexing
    max_pages: batas maksimum halaman (untuk testing)
    save_debug_first: simpan HTML halaman pertama untuk debug
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
                # Simpan debug untuk halaman pertama
                save_debug = (save_debug_first and i == 0)
                metadata = extract_metadata_with_bs4(url, response.text, save_debug)
                results.append(metadata)
                print(f"   ✅ Title: {metadata['title']}")
                print(f"      Original: {metadata['original_title']}")
                print(f"      Season: {metadata['season']}, Episode: {metadata['episode']}")
                print(f"      Image: {metadata['image']}")
            else:
                print(f"   ❌ Status: {response.status_code}")
            
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
# 5. EKSEKUSI
# ============================================================

if __name__ == "__main__":
    import sys
    
    max_pages = None
    save_debug = False
    
    if len(sys.argv) > 1:
        try:
            max_pages = int(sys.argv[1])
            print(f"🔧 Argumen: hanya {max_pages} halaman")
        except ValueError:
            if sys.argv[1].lower() == '--debug':
                save_debug = True
                print("🔧 Mode debug: HTML pertama akan disimpan")
    
    print("=" * 50)
    print("🚀 PENGEPUL-LINK - Crawler & Scraper 9tsu.in (BS4)")
    print("=" * 50)
    
    crawl_and_index(max_pages, save_debug)
