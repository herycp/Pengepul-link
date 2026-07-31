#!/usr/bin/env python3
"""
Ekstrak semua link artikel dari 9tsu.vip
"""

import json
import re
import time
from datetime import datetime
from urllib.parse import urljoin

import cloudscraper
from bs4 import BeautifulSoup

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

scraper = cloudscraper.create_scraper()


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
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    
    for attempt in range(max_retries):
        try:
            print(f"  🔄 Attempt {attempt+1}...")
            resp = scraper.get(url, headers=headers, timeout=30)
            
            if resp.status_code == 200:
                print(f"  ✅ Success ({len(resp.text)} bytes)")
                return resp.text
            else:
                print(f"  ⚠️ Status: {resp.status_code}")
        except Exception as e:
            print(f"  ⚠️ Error: {e}")
            
        time.sleep(3)
    
    return None


def extract_links_from_page(html, base_url):
    """Ekstrak semua link artikel dari halaman"""
    soup = BeautifulSoup(html, "html.parser")
    links = []
    
    # ===== DEBUG: Tulis HTML ke file untuk inspect =====
    with open("debug.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  📝 Debug HTML saved to debug.html")
    
    # ===== CARI SEMUA LINK =====
    all_links = soup.find_all("a", href=True)
    print(f"  🔗 Total links in page: {len(all_links)}")
    
    # Filter link yang menuju ke artikel drama
    drama_links = []
    for a in all_links:
        href = a.get("href", "")
        if not href:
            continue
            
        # Build full URL
        if href.startswith("/"):
            full_url = urljoin(base_url, href)
        else:
            full_url = href
            
        # Cek apakah ini link artikel (biasanya mengandung /drama/ atau /movie/)
        if "/drama/" in full_url or "/movie/" in full_url or "/film/" in full_url:
            title = a.text.strip()
            if not title:
                # Coba cari di parent
                parent = a.parent
                if parent:
                    title_elem = parent.select_one("h2, h3, h4, .title, .entry-title")
                    if title_elem:
                        title = title_elem.text.strip()
            
            if title:
                clean_title, season, episode = parse_title(title)
                drama_links.append({
                    "url": full_url,
                    "title": clean_title,
                    "original_title": title,
                    "season": season,
                    "episode": episode,
                    "image": None,
                    "source_page": base_url,
                })
    
    # Jika tidak ada link drama, coba cari dari artikel
    if not drama_links:
        # Cari semua artikel
        articles = soup.select("article, .post, .entry, .item, .video-item, .blog-item, .hentry")
        print(f"  📄 Articles found: {len(articles)}")
        
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
                
            # Cari gambar
            img_elem = article.select_one("img")
            img_url = None
            if img_elem:
                img_url = img_elem.get("data-src") or img_elem.get("src")
                
            clean_title, season, episode = parse_title(title)
            
            drama_links.append({
                "url": full_url,
                "title": clean_title,
                "original_title": title,
                "season": season,
                "episode": episode,
                "image": img_url,
                "source_page": base_url,
            })
    
    return drama_links


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
            print(f"  ❌ Gagal mengambil halaman")
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
