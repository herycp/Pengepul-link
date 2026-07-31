#!/usr/bin/env python3
"""
Ekstrak semua link artikel dari 9tsu.vip
Menggunakan Cloudscraper untuk bypass Cloudflare
"""

import json
import re
import time
from datetime import datetime
from urllib.parse import urljoin

try:
    import cloudscraper
except ImportError:
    print("Instal cloudscraper: pip install cloudscraper")
    exit(1)

# Konfigurasi
BASE_URL = "https://9tsu.vip"

# Daftar halaman yang akan di-scrape
PAGES = [
    "/",
    "/daily",
    "/drama-monday1",
    "/drama-tuesday1",
    "/drama-wednesdaydouga",
    "/drama-thursdaydouga",
    "/drama-fridaydouga",
    "/drama-saturdaydouga",
    "/drama-sundaydouga",
    "/dramaend",
    "/premium",
]

# Buat scraper dengan konfigurasi yang tepat
scraper = cloudscraper.create_scraper(
    browser={
        'browser': 'chrome',
        'platform': 'windows',
        'mobile': False,
        'custom': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        }
    }
)


def parse_title(title):
    """Ekstrak judul, season, episode dari string judul"""
    if not title:
        return "", 1, None

    original = title.strip()
    clean_title = original
    season = 1
    episode = None

    patterns = [
        (r'(.*?)\s*Season\s*(\d+)\s*(?:Episode\s*|第)(\d+)[話話]?', 3),
        (r'(.*?)\s*Season\s*(\d+)\s*[-–]\s*(?:Episode\s*|第)(\d+)[話話]?', 3),
        (r'(.*?)\s*S(\d+)E(\d+)', 3),
        (r'(.*?)\s*Season\s*(\d+)', 2),
        (r'(.*?)\s*第(\d+)[話話]', 2),
        (r'(.*?)\s*Episode\s*(\d+)', 2),
        (r'(.*?)\s*Ep\.?\s*(\d+)', 2),
        (r'(.*?)\s*Eps\.?\s*(\d+)', 2),
        (r'(.*?)\s*#(\d+)', 2),
        (r'(.*?)\s*[-–]\s*(?:Episode\s*|第)(\d+)[話話]?', 2),
        (r'(.*?)\s*(\d+)[話話]', 2),
    ]

    for pattern, group_count in patterns:
        match = re.search(pattern, original, re.IGNORECASE)
        if match:
            groups = match.groups()
            if group_count == 3:
                clean_title = groups[0].strip()
                season = int(groups[1])
                episode = int(groups[2])
            elif group_count == 2:
                clean_title = groups[0].strip()
                episode = int(groups[1])
            break

    if not clean_title:
        clean_title = original

    return clean_title, season, episode


def get_page(url, max_retries=3):
    """Fetch halaman dengan cloudscraper"""
    for attempt in range(max_retries):
        try:
            print(f"  🔄 Attempt {attempt+1}...")
            resp = scraper.get(url, timeout=30)
            
            if resp.status_code == 200:
                print(f"  ✅ Success")
                return resp.text
            else:
                print(f"  ⚠️ Status: {resp.status_code}")
                if resp.status_code == 403:
                    # Coba dengan User-Agent berbeda
                    scraper.headers.update({
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                    })
                    resp2 = scraper.get(url, timeout=30)
                    if resp2.status_code == 200:
                        return resp2.text
                        
        except Exception as e:
            print(f"  ⚠️ Error: {e}")
            
        time.sleep(2)
    
    return None


def extract_links_from_page(html, base_url):
    """Ekstrak semua link artikel dari halaman"""
    soup = BeautifulSoup(html, "lxml")
    links = []

    # Cari semua elemen artikel
    articles = soup.select("article, .post, .entry, .type-post, .item, .video-item, .blog-item")
    
    # Jika tidak ada, ambil dari div utama
    if not articles:
        content_div = soup.select_one(".content, .main, #content, .site-content, .container")
        if content_div:
            articles = content_div.select("a[href]")
        else:
            articles = soup.find_all("a", href=True)

    for article in articles:
        # Cari judul
        title_elem = article.select_one("h2 a, h3 a, h4 a, .entry-title a, .post-title a, a[rel='bookmark']")
        if not title_elem:
            continue

        title = title_elem.text.strip()
        href = title_elem.get("href")
        if not href:
            continue

        full_url = urljoin(base_url, href)
        if not full_url.startswith("http"):
            continue
            
        # Filter link yang tidak relevan
        skip_patterns = ["/category/", "/tag/", "/page/", "/author/", "/wp-", "#", "?s=", "/search/", "/feed/"]
        if any(p in full_url for p in skip_patterns):
            continue

        # Cari gambar
        img_elem = article.select_one("img")
        img_url = None
        if img_elem:
            img_url = img_elem.get("data-src") or img_elem.get("src") or img_elem.get("data-lazy-src")
            if img_url and (img_url.startswith("data:image") or "placeholder" in img_url):
                img_url = None

        # Parse season dan episode
        clean_title, season, episode = parse_title(title)

        links.append({
            "url": full_url,
            "title": clean_title,
            "original_title": title,
            "season": season,
            "episode": episode,
            "image": img_url,
            "source_page": base_url,
        })

    return links


def main():
    print("=" * 60)
    print("9TSU LINK EXTRACTOR")
    print(f"Waktu: {datetime.now().isoformat()}")
    print("=" * 60)

    all_links = []
    seen_urls = set()

    for page in PAGES:
        url = urljoin(BASE_URL, page)
        print(f"\n📄 Memproses: {url}")
        html = get_page(url)
        if not html:
            print(f"  ❌ Gagal")
            continue

        links = extract_links_from_page(html, url)
        print(f"  ✅ Ditemukan {len(links)} link")

        for link in links:
            if link["url"] not in seen_urls:
                seen_urls.add(link["url"])
                all_links.append(link)

    print(f"\n📊 Total link unik: {len(all_links)}")

    output = {
        "timestamp": datetime.now().isoformat(),
        "total": len(all_links),
        "links": all_links,
    }

    with open("links.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    with open("urls.txt", "w", encoding="utf-8") as f:
        for link in all_links:
            f.write(link["url"] + "\n")

    print(f"\n💾 Disimpan ke links.json dan urls.txt")
    print("✅ Selesai!")


if __name__ == "__main__":
    main()
