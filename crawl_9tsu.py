import cloudscraper
import xml.etree.ElementTree as ET
import json
import re
import time
from datetime import datetime
from urllib.parse import urlparse

# ============================================================
# 1. HEADERS - Seperti Browser Nyata
# ============================================================

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
    "Referer": "https://9tsu.vip/"
}


# ============================================================
# 2. FUNGSI PARSING TITLE, SEASON, EPISODE
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
# 3. FUNGSI EKSTRAK URL DARI SITEMAP
# ============================================================

def get_all_article_urls():
    """
    Ambil semua URL artikel dari sitemap_index.xml
    Menggunakan cloudscraper untuk melewati Cloudflare/anti-bot
    """
    sitemap_index_url = "https://9tsu.vip/sitemap_index.xml"
    
    try:
        print("📡 Mengambil daftar URL dari sitemap...")
        
        # Buat scraper dengan cloudscraper
        scraper = cloudscraper.create_scraper()
        
        # Tambahkan headers
        scraper.headers.update(HEADERS)
        
        response = scraper.get(sitemap_index_url, timeout=60)
        response.raise_for_status()
        
        # Parse XML sitemap index
        root = ET.fromstring(response.content)
        ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        
        all_urls = []
        # Cari semua tag <loc> di dalam <sitemap>
        for loc in root.findall('.//ns:loc', ns):
            sitemap_url = loc.text
            if sitemap_url:
                # Ambil URL dari setiap sitemap
                urls = extract_urls_from_sitemap(sitemap_url)
                all_urls.extend(urls)
                time.sleep(0.5)  # Jeda antar sitemap
        
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
                # Filter: hanya URL artikel (biasanya .html atau /drama/)
                if '/drama/' in url or url.endswith('.html'):
                    urls.append(url)
        return urls
    except Exception as e:
        print(f"⚠️ Error parsing sitemap {sitemap_url}: {e}")
        return []


# ============================================================
# 4. FUNGSI EKSTRAK METADATA DARI HALAMAN
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
    
    # Ambil judul dari tag <title>
    title_match = re.search(r'<title>(.*?)</title>', html_content, re.IGNORECASE | re.DOTALL)
    if title_match:
        raw_title = title_match.group(1).strip()
        # Bersihkan judul dari teks tambahan
        raw_title = re.sub(r'\s*[-|]\s*9tsu.*$', '', raw_title).strip()
        raw_title = re.sub(r'\s*[-|]\s*[Dd]ailymotion.*$', '', raw_title).strip()
        raw_title = re.sub(r'\s*[-|]\s*[Mm]iomio.*$', '', raw_title).strip()
        
        metadata["original_title"] = raw_title
        
        # Parsing title, season, episode dari original_title
        title, season, episode = parse_title_season_episode(raw_title)
        metadata["title"] = title
        metadata["season"] = season
        metadata["episode"] = episode
    
    # Ambil gambar dari meta og:image
    img_match = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html_content, re.IGNORECASE)
    if img_match:
        metadata["image"] = img_match.group(1)
    else:
        # Fallback: cari gambar dari tag img
        img_match2 = re.search(r'<img[^>]+src="([^"]+\.(jpg|jpeg|png|gif))"', html_content, re.IGNORECASE)
        if img_match2:
            metadata["image"] = img_match2.group(1)
    
    metadata["source_page"] = "https://9tsu.vip/"
    
    return metadata


# ============================================================
# 5. FUNGSI UTAMA CRAWL & INDEX
# ============================================================

def crawl_and_index(max_pages=None):
    """
    Fungsi utama crawling dan indexing
    max_pages: batas maksimum halaman yang diproses (untuk testing)
    """
    # Ambil semua URL dari sitemap
    urls = get_all_article_urls()
    
    if not urls:
        print("⚠️ Gagal mengambil URL dari sitemap. Mencoba metode alternatif...")
        urls = get_urls_from_homepage()
    
    if not urls:
        print("❌ Tidak ada URL yang ditemukan.")
        return None
    
    # Batasi jumlah untuk testing
    if max_pages:
        urls = urls[:max_pages]
    
    print(f"✅ Ditemukan {len(urls)} URL artikel")
    
    results = []
    scraper = cloudscraper.create_scraper()
    scraper.headers.update(HEADERS)
    
    for i, url in enumerate(urls):
        try:
            print(f"🔄 Memproses [{i+1}/{len(urls)}]: {url[:80]}...")
            
            response = scraper.get(url, timeout=60)
            response.raise_for_status()
            
            if response.status_code == 200:
                metadata = extract_metadata(url, response.text)
                if metadata["title"]:
                    results.append(metadata)
                    print(f"   ✅ {metadata['title']} (S{metadata['season']} E{metadata['episode']})")
                else:
                    print(f"   ⚠️ Tidak ada title yang ditemukan")
            
            # Jeda antar request untuk menghormati server
            time.sleep(1.5)
            
        except Exception as e:
            print(f"❌ Error pada {url}: {e}")
    
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
# 6. FUNGSI FALLBACK (jika sitemap gagal)
# ============================================================

def get_urls_from_homepage():
    """
    Fallback: scraping dari homepage jika sitemap tidak tersedia
    """
    urls = []
    try:
        scraper = cloudscraper.create_scraper()
        scraper.headers.update(HEADERS)
        
        print("📥 Mencoba fallback dari homepage...")
        response = scraper.get("https://9tsu.vip/", timeout=60)
        response.raise_for_status()
        
        # Cari semua link menuju artikel
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
# 7. EKSEKUSI
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
