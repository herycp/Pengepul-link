import requests
import xml.etree.ElementTree as ET
import json
import re
import time
from datetime import datetime
from urllib.parse import urlparse

# ============================================================
# 1. FUNGSI PARSING TITLE, SEASON, EPISODE
# ============================================================

def parse_title_season_episode(original_title):
    """
    Parsing judul untuk mendapatkan:
    - title: judul utama (tanpa season/episode)
    - season: nomor season (int)
    - episode: nomor episode (int)
    
    Aturan khusus:
    - Jika ada episode tetapi season = None, maka season dianggap 1
    """
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

    # Pola 2: "Judul 第5話" (hanya episode, tanpa season) -> season = 1
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

    # Jika tidak ada pola yang cocok
    return title, None, None


# ============================================================
# 2. FUNGSI EKSTRAK URL DARI SITEMAP
# ============================================================

def get_all_article_urls():
    """
    Ambil semua URL artikel dari sitemap_index.xml
    """
    sitemap_index_url = "https://9tsu.vip/sitemap_index.xml"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    try:
        print("📡 Mengambil daftar URL dari sitemap...")
        response = requests.get(sitemap_index_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        root = ET.fromstring(response.content)
        ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        
        all_urls = []
        for loc in root.findall('.//ns:loc', ns):
            sitemap_url = loc.text
            if sitemap_url:
                urls = extract_urls_from_sitemap(sitemap_url, headers)
                all_urls.extend(urls)
                time.sleep(0.5)
        
        return all_urls
    except Exception as e:
        print(f"❌ Error fetching sitemap: {e}")
        return []


def extract_urls_from_sitemap(sitemap_url, headers):
    """
    Ekstrak URL dari satu file sitemap
    """
    try:
        response = requests.get(sitemap_url, headers=headers, timeout=30)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        
        urls = []
        for loc in root.findall('.//ns:loc', ns):
            url = loc.text
            if url and ('/drama/' in url or url.endswith('.html')):
                urls.append(url)
        return urls
    except Exception as e:
        print(f"⚠️ Error parsing sitemap {sitemap_url}: {e}")
        return []


# ============================================================
# 3. FUNGSI EKSTRAK METADATA DARI HALAMAN
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
        "source_page": None
    }
    
    title_match = re.search(r'<title>(.*?)</title>', html_content, re.IGNORECASE | re.DOTALL)
    if title_match:
        raw_title = title_match.group(1).strip()
        raw_title = re.sub(r'\s*[-|]\s*9tsu.*$', '', raw_title).strip()
        raw_title = re.sub(r'\s*[-|]\s*[Dd]ailymotion.*$', '', raw_title).strip()
        raw_title = re.sub(r'\s*[-|]\s*[Mm]iomio.*$', '', raw_title).strip()
        
        metadata["original_title"] = raw_title
        title, season, episode = parse_title_season_episode(raw_title)
        metadata["title"] = title
        metadata["season"] = season
        metadata["episode"] = episode
    
    img_match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html_content, re.IGNORECASE)
    if img_match:
        metadata["image"] = img_match.group(1)
    else:
        img_match2 = re.search(r'<img[^>]+src="([^"]+\.(jpg|jpeg|png|gif))"', html_content, re.IGNORECASE)
        if img_match2:
            metadata["image"] = img_match2.group(1)
    
    metadata["source_page"] = "https://9tsu.vip/"
    return metadata


# ============================================================
# 4. FUNGSI UTAMA CRAWL & INDEX
# ============================================================

def crawl_and_index(max_pages=None):
    urls = get_all_article_urls()
    
    if not urls:
        print("⚠️ Gagal mengambil URL dari sitemap. Mencoba metode alternatif...")
        urls = get_urls_from_homepage()
    
    if not urls:
        print("❌ Tidak ada URL yang ditemukan.")
        return None
    
    if max_pages:
        urls = urls[:max_pages]
    
    print(f"✅ Ditemukan {len(urls)} URL artikel")
    
    results = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    for i, url in enumerate(urls):
        try:
            print(f"🔄 Memproses [{i+1}/{len(urls)}]: {url[:80]}...")
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            if response.status_code == 200:
                metadata = extract_metadata(url, response.text)
                if metadata["title"]:
                    results.append(metadata)
                    print(f"   ✅ {metadata['title']} (S{metadata['season']} E{metadata['episode']})")
                else:
                    print(f"   ⚠️ Tidak ada title yang ditemukan")
            
            time.sleep(1)
            
        except Exception as e:
            print(f"❌ Error pada {url}: {e}")
    
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
# 5. FUNGSI FALLBACK
# ============================================================

def get_urls_from_homepage():
    urls = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        response = requests.get("https://9tsu.vip/", headers=headers, timeout=30)
        response.raise_for_status()
        pattern = r'href="(/\d+\.html)"'
        matches = re.findall(pattern, response.text)
        for match in matches:
            full_url = f"https://9tsu.vip{match}"
            if full_url not in urls:
                urls.append(full_url)
        print(f"📥 Fallback: mendapatkan {len(urls)} URL dari homepage")
    except Exception as e:
        print(f"❌ Fallback error: {e}")
    return urls


# ============================================================
# 6. EKSEKUSI
# ============================================================

if __name__ == "__main__":
    import sys
    
    max_pages = None
    if len(sys.argv) > 1:
        try:
            max_pages = int(sys.argv[1])
            print(f"🔧 Mode testing: hanya {max_pages} halaman")
        except ValueError:
            print("⚠️ Argumen harus berupa angka. Menggunakan semua halaman.")
    
    print("=" * 50)
    print("🚀 PENGEPUL-LINK - Crawler & Indexer 9tsu.vip")
    print("=" * 50)
    
    crawl_and_index(max_pages)
