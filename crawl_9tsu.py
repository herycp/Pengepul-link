import cloudscraper
import xml.etree.ElementTree as ET
import json
import re
import time
import os
from datetime import datetime
from urllib.parse import urlparse
from bs4 import BeautifulSoup

# ============================================================
# 1. KONFIGURASI
# ============================================================

BASE_URL = "https://9tsu.in"
SITEMAP_INDEX = f"{BASE_URL}/sitemap_index.xml"
HTML_DIR = "html_pages"

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
# 2. FUNGSI MEMBUAT DIREKTORI
# ============================================================

def create_directory():
    """Buat direktori untuk menyimpan HTML jika belum ada"""
    if not os.path.exists(HTML_DIR):
        os.makedirs(HTML_DIR)
        print(f"📁 Direktori dibuat: {HTML_DIR}")
    return HTML_DIR


# ============================================================
# 3. DOWNLOAD DAN SIMPAN HTML (DIPERBAIKI)
# ============================================================

def download_and_save_html(url, scraper, save_html=True):
    """
    Download HTML dari URL dan simpan ke file dengan encoding yang benar
    Returns: (html_content, filename, status_code)
    """
    try:
        response = scraper.get(url, timeout=60)
        
        if response.status_code == 200:
            # 🔥 PERBAIKAN 1: Pastikan encoding benar
            if response.encoding is None:
                response.encoding = 'utf-8'
            
            # 🔥 PERBAIKAN 2: Dapatkan konten sebagai text
            html_content = response.text
            
            # 🔥 PERBAIKAN 3: Cek apakah konten valid (bukan binary)
            if html_content and not html_content.strip().startswith('<?xml'):
                try:
                    html_content.encode('utf-8')
                except UnicodeEncodeError:
                    html_content = response.content.decode('utf-8', errors='ignore')
            
            if save_html:
                parsed = urlparse(url)
                path = parsed.path.strip('/')
                if not path:
                    path = 'index'
                filename = path.replace('/', '_') + '.html'
                filepath = os.path.join(HTML_DIR, filename)
                
                # 🔥 PERBAIKAN 4: Simpan dengan encoding UTF-8
                with open(filepath, 'w', encoding='utf-8', errors='ignore') as f:
                    f.write(html_content)
                
                return html_content, filepath, 200
            else:
                return html_content, None, 200
        else:
            return None, None, response.status_code
            
    except Exception as e:
        print(f"   ❌ Download error: {e}")
        return None, None, 0


# ============================================================
# 4. PARSE HTML DENGAN BEAUTIFULSOUP
# ============================================================

def parse_html_page(html_content, url):
    """
    Parse HTML untuk mengekstrak metadata
    """
    metadata = {
        "url": url,
        "title": None,
        "original_title": None,
        "season": None,
        "episode": None,
        "image": None,
        "source_page": BASE_URL,
        "html_file": None
    }
    
    if not html_content:
        return metadata
    
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Cek apakah ada tag html
        if not soup.find('html'):
            print(f"   ⚠️ Konten tidak valid HTML, mencoba alternatif...")
            return parse_html_with_regex(html_content, url)
            
    except Exception as e:
        print(f"   ⚠️ Error parsing with BeautifulSoup: {e}")
        return parse_html_with_regex(html_content, url)
    
    # --- 1. ORIGINAL TITLE ---
    og_title = soup.find('meta', property='og:title')
    if og_title and og_title.get('content'):
        metadata["original_title"] = og_title['content'].strip()
    else:
        title_tag = soup.find('title')
        if title_tag:
            metadata["original_title"] = title_tag.get_text(strip=True)
    
    # --- 2. TITLE BERSIH ---
    cleaned_title = None
    
    article_section = soup.find('meta', property='article:section')
    if article_section and article_section.get('content'):
        cleaned_title = article_section['content'].strip()
    
    if not cleaned_title and og_title and og_title.get('content'):
        cleaned_title = og_title['content'].strip()
        cleaned_title = re.sub(r'\s*第\d+話\s*', '', cleaned_title)
        cleaned_title = re.sub(r'\s*Season\s*\d+\s*', '', cleaned_title, flags=re.IGNORECASE)
        cleaned_title = re.sub(r'\s*[-|]\s*9tsu.*$', '', cleaned_title)
        cleaned_title = re.sub(r'\s*[-|]\s*[Dd]ailymotion.*$', '', cleaned_title)
        cleaned_title = re.sub(r'\s*[-|]\s*[Mm]iomio.*$', '', cleaned_title)
        cleaned_title = re.sub(r'\s*[-|]\s*[Yy]outube.*$', '', cleaned_title)
        cleaned_title = cleaned_title.strip()
    
    if not cleaned_title:
        h1 = soup.find('h1')
        if h1:
            cleaned_title = h1.get_text(strip=True)
            cleaned_title = re.sub(r'\s*第\d+話\s*', '', cleaned_title)
            cleaned_title = re.sub(r'\s*Season\s*\d+\s*', '', cleaned_title, flags=re.IGNORECASE)
            cleaned_title = cleaned_title.strip()
    
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
    html_text = soup.get_text()
    
    pattern1 = r'Season\s*(\d+)\s*[　]?\s*第(\d+)話'
    match = re.search(pattern1, html_text, re.IGNORECASE)
    if match:
        metadata["season"] = int(match.group(1))
        metadata["episode"] = int(match.group(2))
    else:
        pattern2 = r'第(\d+)話'
        match = re.search(pattern2, html_text)
        if match:
            metadata["season"] = 1
            metadata["episode"] = int(match.group(1))
        else:
            pattern3 = r'[sS](\d+)[eE](\d+)'
            match = re.search(pattern3, html_text)
            if match:
                metadata["season"] = int(match.group(1))
                metadata["episode"] = int(match.group(2))
    
    # --- 4. IMAGE ---
    og_image = soup.find('meta', property='og:image')
    if og_image and og_image.get('content'):
        metadata["image"] = og_image['content'].strip()
    
    return metadata


# ============================================================
# 5. FALLBACK PARSING DENGAN REGEX
# ============================================================

def parse_html_with_regex(html_content, url):
    """
    Fallback parsing dengan Regex jika BeautifulSoup gagal
    """
    metadata = {
        "url": url,
        "title": None,
        "original_title": None,
        "season": None,
        "episode": None,
        "image": None,
        "source_page": BASE_URL,
        "html_file": None
    }
    
    try:
        # Cari title
        title_match = re.search(r'<title>(.*?)</title>', html_content, re.IGNORECASE | re.DOTALL)
        if title_match:
            raw_title = title_match.group(1).strip()
            metadata["original_title"] = raw_title
            cleaned = re.sub(r'\s*第\d+話\s*', '', raw_title)
            cleaned = re.sub(r'\s*Season\s*\d+\s*', '', cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r'\s*[-|]\s*9tsu.*$', '', cleaned)
            cleaned = re.sub(r'\s*[-|]\s*[Dd]ailymotion.*$', '', cleaned)
            cleaned = re.sub(r'\s*[-|]\s*[Mm]iomio.*$', '', cleaned)
            cleaned = re.sub(r'\s*[-|]\s*[Yy]outube.*$', '', cleaned)
            metadata["title"] = cleaned.strip()
        
        # Cari season & episode
        season_match = re.search(r'Season\s*(\d+)\s*[　]?\s*第(\d+)話', html_content, re.IGNORECASE)
        if season_match:
            metadata["season"] = int(season_match.group(1))
            metadata["episode"] = int(season_match.group(2))
        else:
            episode_match = re.search(r'第(\d+)話', html_content)
            if episode_match:
                metadata["season"] = 1
                metadata["episode"] = int(episode_match.group(1))
        
        # Cari image
        image_match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html_content, re.IGNORECASE)
        if image_match:
            metadata["image"] = image_match.group(1).strip()
            
    except Exception as e:
        print(f"   ❌ Regex fallback error: {e}")
    
    return metadata


# ============================================================
# 6. AMBIL URL DARI SITEMAP
# ============================================================

def get_all_article_urls():
    """Ambil semua URL artikel dari sitemap (hanya post-sitemap)"""
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
    """Ekstrak URL dari satu file sitemap"""
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
# 7. FUNGSI UTAMA
# ============================================================

def crawl_and_index(max_pages=None):
    """Fungsi utama crawling dan indexing"""
    create_directory()
    
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
        print(f"\n🔄 [{i+1}/{len(urls)}] {url}")
        print("-" * 60)
        
        html_content, html_file, status = download_and_save_html(url, scraper, save_html=True)
        
        if status == 200 and html_content:
            print(f"   ✅ HTML berhasil di-download")
            print(f"   📄 Disimpan di: {html_file}")
            
            metadata = parse_html_page(html_content, url)
            metadata["html_file"] = html_file
            
            print(f"   📝 Hasil parsing:")
            print(f"      - Title: {metadata['title']}")
            print(f"      - Original: {metadata['original_title']}")
            print(f"      - Season: {metadata['season']}")
            print(f"      - Episode: {metadata['episode']}")
            print(f"      - Image: {metadata['image']}")
            
            results.append(metadata)
        else:
            print(f"   ❌ Gagal download HTML (status: {status})")
            metadata = {
                "url": url,
                "title": None,
                "original_title": None,
                "season": None,
                "episode": None,
                "image": None,
                "source_page": BASE_URL,
                "html_file": None,
                "error": f"HTTP {status}"
            }
            results.append(metadata)
        
        time.sleep(1)
    
    output = {
        "timestamp": datetime.now().isoformat(),
        "total": len(results),
        "links": results
    }
    
    with open("links.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    successful = sum(1 for r in results if r.get('title'))
    print("\n" + "=" * 60)
    print(f"✅ Selesai!")
    print(f"📊 Total: {len(results)} link diproses")
    print(f"✅ Berhasil parsing: {successful}")
    print(f"❌ Gagal: {len(results) - successful}")
    print(f"📁 HTML disimpan di: {HTML_DIR}/")
    print(f"📁 JSON disimpan di: links.json")
    print("=" * 60)
    
    return output


# ============================================================
# 8. EKSEKUSI
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
    
    print("=" * 60)
    print("🚀 PENGEPUL-LINK - Crawler & Scraper 9tsu.in")
    print("📌 Mode: Download HTML + Parse + Save")
    print("=" * 60)
    
    crawl_and_index(max_pages)
