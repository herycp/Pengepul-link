#!/usr/bin/env python3
import sys
import time
import json
from datetime import datetime
import cloudscraper  # wajib install: pip install cloudscraper
from bs4 import BeautifulSoup
import re

# ========== KONFIGURASI ==========
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
TIMEOUT = 15
DELAY = 2  # jeda antar request (detik)
# =================================

def get_page(url):
    """Mengambil konten HTML dengan cloudscraper + header"""
    scraper = cloudscraper.create_scraper()
    headers = {"User-Agent": USER_AGENT}
    try:
        print(f"Memproses: {url}")
        resp = scraper.get(url, headers=headers, timeout=TIMEOUT)
        if resp.status_code == 200:
            return resp.text
        else:
            print(f"Status {resp.status_code} untuk {url}")
            return None
    except Exception as e:
        print(f"Gagal mengambil {url}: {e}")
        return None

def extract_links_from_html(html, base_url):
    """Ekstrak semua link video (misal dari tag <a> atau <source>)"""
    soup = BeautifulSoup(html, 'html.parser')
    links = set()

    # Cari link di tag <a> yang mengandung kata 'download' atau 'video'
    for a in soup.find_all('a', href=True):
        href = a['href']
        if 'download' in href.lower() or '.mp4' in href or '/video/' in href:
            full_url = href if href.startswith('http') else base_url.rstrip('/') + '/' + href.lstrip('/')
            links.add(full_url)

    # Cari juga di tag <source> (biasa untuk video player)
    for source in soup.find_all('source', src=True):
        src = source['src']
        full_url = src if src.startswith('http') else base_url.rstrip('/') + '/' + src.lstrip('/')
        links.add(full_url)

    # Cari pola URL video di dalam script atau atribut (jika ada)
    # Contoh pola: https://cdn.9tsu.vip/.../video.mp4
    pattern = r'https?://[^\s"\']+\.(?:mp4|m3u8|ts|avi|mkv)'
    found = re.findall(pattern, html)
    for f in found:
        links.add(f)

    return list(links)

def main():
    # Baca daftar URL dari argumen atau dari file? 
    # Di log terlihat ada 3 URL: https://9tsu.vip/, daily, drama-monday1
    # Kita ambil dari sys.argv atau pakai daftar default

    if len(sys.argv) > 1:
        urls = sys.argv[1:]  # bisa kasih banyak URL
    else:
        # Default: daftar URL yang ingin di-scrape
        urls = [
            "https://9tsu.vip/",
            "https://9tsu.vip/daily",
            "https://9tsu.vip/drama-monday1"
        ]

    print("=" * 50)
    print("9TSU_LINK_EXTRACTOR")
    print(f"Waktu: {datetime.now().isoformat()}")
    print("=" * 50)
    print()

    all_links = {}

    for url in urls:
        html = get_page(url)
        if html:
            links = extract_links_from_html(html, url)
            all_links[url] = links
            print(f"  -> Ditemukan {len(links)} link dari {url}")
        else:
            all_links[url] = []
            print(f"  -> Gagal mengambil {url}")
        time.sleep(DELAY)  # jeda biar tidak dianggap spam

    # Tampilkan hasil akhir
    print("\n" + "=" * 50)
    print("HASIL EKSTRAKSI")
    print("=" * 50)
    total = 0
    for url, links in all_links.items():
        print(f"\n{url}")
        for i, link in enumerate(links, 1):
            print(f"  {i}. {link}")
        total += len(links)
    print(f"\nTotal link ditemukan: {total}")

    # Simpan ke file JSON (opsional)
    with open("extracted_links.json", "w") as f:
        json.dump(all_links, f, indent=2, ensure_ascii=False)
    print("Hasil juga disimpan ke extracted_links.json")

if __name__ == "__main__":
    main()
