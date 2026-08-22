import cloudscraper
import xml.etree.ElementTree as ET
import json
import time
import os
import sqlite3
import concurrent.futures
from bs4 import BeautifulSoup

# ============================================================
# 1. KONFIGURASI & EXCLUSION LIST
# ============================================================
SITEMAP_URL = "https://9tsu.in/category-sitemap.xml"
AJAX_URL = "https://9tsu.in/wp-admin/admin-ajax.php"
OUTPUT_JSON = "categories_data.json"
OUTPUT_DB = "categories.db"
MAX_WORKERS = 5

EXCLUDED_CATEGORIES = {
    "drama", "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday", "daily", "movie", "spmovies",
    "premium", "housou-shuuryou", "dramaend", "youtube-baraeti"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://9tsu.in/"
}

scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False},
    delay=True
)
scraper.headers.update(HEADERS)

# ============================================================
# 2. MANAJEMEN DATABASE SQLITE
# ============================================================
def init_database():
    conn = sqlite3.connect(OUTPUT_DB)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS categories (
            category_name TEXT PRIMARY KEY,
            category_title TEXT,
            category_url TEXT,
            sitemap_lastmod TEXT,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    try:
        cursor.execute('ALTER TABLE categories ADD COLUMN sitemap_lastmod TEXT')
    except sqlite3.OperationalError:
        pass
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS category_episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_name TEXT,
            episode_title TEXT,
            episode_url TEXT,
            episode_image TEXT,
            UNIQUE(category_name, episode_url),
            FOREIGN KEY (category_name) REFERENCES categories (category_name)
        )
    ''')

    # Migrasi tabel lama: Menambahkan kolom gambar jika belum ada
    try:
        cursor.execute('ALTER TABLE category_episodes ADD COLUMN episode_image TEXT')
    except sqlite3.OperationalError:
        pass
    
    conn.commit()
    conn.close()

def get_db_lastmods():
    conn = sqlite3.connect(OUTPUT_DB)
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT category_name, sitemap_lastmod FROM categories')
        db_lastmods = dict(cursor.fetchall())
    except sqlite3.OperationalError:
        db_lastmods = {}
    conn.close()
    return db_lastmods

def get_existing_episodes(category_name):
    conn = sqlite3.connect(OUTPUT_DB)
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT episode_url FROM category_episodes WHERE category_name = ?', (category_name,))
        urls = {row[0] for row in cursor.fetchall()}
    except sqlite3.OperationalError:
        urls = set()
    conn.close()
    return urls

def save_to_database(all_data):
    if not all_data:
        return
        
    conn = sqlite3.connect(OUTPUT_DB)
    cursor = conn.cursor()
    total_new_episodes = 0
    
    for cat in all_data:
        cursor.execute('''
            INSERT INTO categories (category_name, category_title, category_url, sitemap_lastmod, last_updated)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(category_name) DO UPDATE SET
                category_title = excluded.category_title,
                category_url = excluded.category_url,
                sitemap_lastmod = excluded.sitemap_lastmod,
                last_updated = CURRENT_TIMESTAMP
        ''', (cat['category_name'], cat['category_title'], cat['category_url'], cat['lastmod']))
        
        if cat['episodes']:
            episodes_payload = [
                (cat['category_name'], ep['title'], ep['url'], ep['image'])
                for ep in cat['episodes'][::-1]
            ]
            
            cursor.executemany('''
                INSERT OR IGNORE INTO category_episodes (category_name, episode_title, episode_url, episode_image)
                VALUES (?, ?, ?, ?)
            ''', episodes_payload)
            
            total_new_episodes += cursor.rowcount

    conn.commit()
    conn.close()
    print(f"💾 Disimpan ke DB: Data kategori diperbarui dan {total_new_episodes} episode BARU ditambahkan.")

def export_db_to_json():
    conn = sqlite3.connect(OUTPUT_DB)
    cursor = conn.cursor()
    
    cursor.execute('SELECT category_name, category_title, category_url, sitemap_lastmod FROM categories ORDER BY category_name')
    categories = cursor.fetchall()
    
    all_data = []
    for cat_name, cat_title, cat_url, cat_lastmod in categories:
        cat_dict = {
            "category_url": cat_url,
            "category_name": cat_name,
            "category_title": cat_title,
            "lastmod": cat_lastmod,
            "episodes": []
        }
        
        cursor.execute('SELECT episode_title, episode_url, episode_image FROM category_episodes WHERE category_name = ? ORDER BY id DESC', (cat_name,))
        episodes = cursor.fetchall()
        
        for ep_title, ep_url, ep_image in episodes:
            cat_dict["episodes"].append({
                "title": ep_title,
                "url": ep_url,
                "image": ep_image
            })
            
        all_data.append(cat_dict)
        
    conn.close()
    
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=4)
    print(f"📦 Sinkronisasi JSON selesai. {len(all_data)} kategori diekspor ke {OUTPUT_JSON}.")

# ============================================================
# 3. FUNGSI SCRAPING
# ============================================================

def get_category_urls():
    print(f"🔍 Mengunduh sitemap: {SITEMAP_URL}")
    response = scraper.get(SITEMAP_URL, timeout=30)
    
    if response.status_code != 200:
        print(f"❌ Gagal mengunduh sitemap (HTTP {response.status_code})")
        return []
        
    try:
        root = ET.fromstring(response.content)
        ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        
        valid_categories = []
        db_lastmods = get_db_lastmods()
        skipped_count = 0
        
        for url_node in root.findall('.//ns:url', ns):
            loc = url_node.find('ns:loc', ns)
            lastmod_node = url_node.find('ns:lastmod', ns)
            
            if loc is not None and loc.text:
                url = loc.text
                lastmod = lastmod_node.text if lastmod_node is not None else None
                category_name = url.strip('/').split('/')[-1]
                
                if category_name in EXCLUDED_CATEGORIES:
                    continue
                    
                db_time = db_lastmods.get(category_name)
                if db_time and db_time == lastmod:
                    skipped_count += 1
                    continue 
                
                valid_categories.append({
                    "url": url,
                    "category_name": category_name,
                    "lastmod": lastmod
                })
                
        print(f"✅ Filter Sitemap Selesai:")
        print(f"   - {skipped_count} kategori dilewati (Tidak ada update).")
        print(f"   - {len(valid_categories)} kategori BUTUH di-scrape.")
        
        return valid_categories
    except Exception as e:
        print(f"❌ Error parsing sitemap: {e}")
        return []

def scrape_single_category(cat_data):
    url = cat_data['url']
    category_name = cat_data['category_name']
    lastmod = cat_data['lastmod']
    
    existing_episodes = get_existing_episodes(category_name)
    
    result = {
        "category_url": url,
        "category_name": category_name,
        "category_title": None,
        "lastmod": lastmod,
        "episodes": []
    }
    
    try:
        res = scraper.get(url, timeout=30)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'lxml')
            
            # REVISI 1: Mengambil judul dari h1.category-title dan membuang span count[span_1](start_span)[span_1](end_span)
            h1 = soup.find('h1', class_='category-title')
            if h1:
                count_span = h1.find('span', class_='category-post-count')
                if count_span:
                    count_span.decompose() # Menghapus elemen span dari h1
                result["category_title"] = h1.get_text(strip=True)
            else:
                result["category_title"] = category_name
        else:
            result["category_title"] = category_name
    except Exception:
        result["category_title"] = category_name

    print(f"⏳ Memproses: {result['category_title']} ({category_name})")

    page = 0
    stop_crawling = False
    
    while not stop_crawling:
        payload = {
            "action": "load_more",
            "page": str(page),
            "template": "html/loop/content",
            "vars[category_name]": category_name
        }
        
        try:
            ajax_res = scraper.post(AJAX_URL, data=payload, timeout=30)
            
            if ajax_res.status_code != 200:
                print(f"  ⚠️ Error HTTP {ajax_res.status_code} pada page {page} kategori {category_name}")
                break
                
            html_content = ajax_res.text
            soup_ajax = BeautifulSoup(html_content, 'lxml')
            
            articles = soup_ajax.find_all('article', class_='cactus-post-item')
            for article in articles:
                title_tag = article.find('h3', class_='cactus-post-title')
                a_tag = title_tag.find('a') if title_tag else article.find('a')
                
                # REVISI 2: Ekstraksi gambar
                img_tag = article.find('img')
                ep_image = None
                if img_tag:
                    # Ambil data-src terlebih dahulu untuk menembus lazyload
                    ep_image = img_tag.get('data-src') or img_tag.get('src')
                
                if a_tag and a_tag.get('href'):
                    ep_title = a_tag.get('title') or a_tag.get_text(strip=True)
                    ep_url = a_tag.get('href')
                    
                    if ep_url in existing_episodes:
                        print(f"  ⏩ Bertemu episode lama, menghentikan pencarian halaman untuk kategori ini.")
                        stop_crawling = True
                        break 
                    
                    result["episodes"].append({
                        "title": ep_title,
                        "url": ep_url,
                        "image": ep_image
                    })
                    
            if stop_crawling:
                break 
                
            if "invi no-posts" in html_content:
                break 
                
            page += 1
            time.sleep(0.5) 
            
        except Exception as e:
            print(f"  ⚠️ Request gagal pada page {page} kategori {category_name}: {e}")
            break

    print(f"  ✅ Selesai: {result['category_title']} -> {len(result['episodes'])} episode BARU ditemukan.")
    return result

def main():
    start_time = time.time()
    
    init_database()
    
    categories = get_category_urls()
    if not categories:
        export_db_to_json()
        print(f"🎉 Proses tuntas dalam waktu {time.time() - start_time:.2f} detik!")
        return

    all_data = []
    
    if categories:
        print(f"🚀 Memulai scraping (Mode Delta + Lastmod) dengan {MAX_WORKERS} workers...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(scrape_single_category, cat) for cat in categories]
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                if res:
                    all_data.append(res)
                    
        save_to_database(all_data)
    
    export_db_to_json()
        
    elapsed = time.time() - start_time
    print(f"🎉 Proses tuntas dalam waktu {elapsed:.2f} detik!")

if __name__ == "__main__":
    main()
