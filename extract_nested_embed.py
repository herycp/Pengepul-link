import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sqlite3
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Config Path (Point langsung ke Root Directory)
BASE_DIR = Path(__file__).resolve().parent.parent

LINKS_DB = BASE_DIR / "links.db"
LINKS_JSON = BASE_DIR / "links.json"

LINKS_DB_BACKUP = BASE_DIR / "links_backup.db"
LINKS_JSON_BACKUP = BASE_DIR / "links_backup.json"

# Header Browser
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://google.com/"
}

def create_resilient_session(retries=3, backoff_factor=0.3):
    session = requests.Session()
    session.headers.update(HEADERS)
    retry_strategy = Retry(
        total=retries,
        read=retries,
        connect=retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=20, pool_maxsize=20)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

def find_embed_candidates(soup, current_url):
    candidates = []

    # Tag <iframe> & <embed>
    for tag in soup.find_all(['iframe', 'embed']):
        src = tag.get('src') or tag.get('data-src') or tag.get('data-lazy-src')
        if src and not src.startswith(('data:', 'javascript:')):
            candidates.append(urljoin(current_url, src))

    # Pattern Regex Script / Player Links
    script_texts = " ".join([script.text for script in soup.find_all('script') if script.text])
    regex_patterns = [
        r'https?://[^\s"\'<>]+\.xyz/[^\s"\'<>]+',
        r'https?://[^\s"\'<>]+/embed/[^\s"\'<>]+',
        r'https?://[^\s"\'<>]+/e/[^\s"\'<>]+',
        r'file:\s*["\'](https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)["\']',
        r'source:\s*["\'](https?://[^\s"\'<>]*)["\']'
    ]

    for pattern in regex_patterns:
        matches = re.findall(pattern, script_texts, re.IGNORECASE)
        for match in matches:
            clean_url = match.strip()
            if clean_url not in candidates:
                candidates.append(urljoin(current_url, clean_url))

    return candidates

def extract_nested_embed(url, session, max_depth=3, timeout=10, current_depth=0):
    if current_depth >= max_depth or not url:
        return url

    try:
        response = session.get(url, timeout=timeout)
        if response.status_code != 200:
            return url

        content_type = response.headers.get('Content-Type', '').lower()
        if 'application/x-mpegurl' in content_type or 'video/' in content_type or url.endswith('.m3u8'):
            return url

        soup = BeautifulSoup(response.text, 'html.parser')
        candidates = find_embed_candidates(soup, url)

        if not candidates:
            return url

        for next_target in candidates:
            if next_target == url:
                continue
            resolved_url = extract_nested_embed(
                url=next_target,
                session=session,
                max_depth=max_depth,
                timeout=timeout,
                current_depth=current_depth + 1
            )
            if resolved_url:
                return resolved_url

        return url

    except Exception:
        return url

def process_item(item, session, max_depth, timeout):
    item_id = item.get("id")
    source_url = item.get("url") or item.get("source_url") or item.get("embed_url")

    if not source_url:
        return item

    final_embed = extract_nested_embed(
        url=source_url,
        session=session,
        max_depth=max_depth,
        timeout=timeout
    )

    updated_item = dict(item)
    updated_item["extracted_embed_url"] = final_embed
    updated_item["last_extracted_at"] = datetime.now(timezone.utc).isoformat()

    status = "SUCCESS" if final_embed != source_url else "UNCHANGED/DIRECT"
    print(f"[{status}] ID: #{item_id} | Input: {source_url[:35]}... ➡️ Extracted: {final_embed[:45]}...")

    return updated_item

def init_sqlite_db(db_path):
    """Menyiapkan koneksi SQLite dan memastikan tabel links ada."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS links (
            id TEXT PRIMARY KEY,
            url TEXT,
            extracted_embed_url TEXT,
            last_extracted_at TEXT
        )
    """)
    conn.commit()
    return conn

def fetch_data_from_db_or_json():
    """Membaca data awal dari links.db atau fallback ke links.json."""
    data_items = []

    if LINKS_DB.exists():
        conn = sqlite3.connect(LINKS_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM links")
            rows = cursor.fetchall()
            for r in rows:
                data_items.append(dict(r))
        except sqlite3.Error as e:
            print(f"⚠️ Warning saat membaca links.db: {e}")
        finally:
            conn.close()

    # Fallback ke links.json jika DB kosong/belum ada
    if not data_items and LINKS_JSON.exists():
        with open(LINKS_JSON, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
            if isinstance(raw_data, list):
                data_items = raw_data
            elif isinstance(raw_data, dict):
                data_items = list(raw_data.values())

    return data_items

def save_data_to_db_and_json(data_items):
    """Memperbarui links.db (SQLite) dan links.json secara bersamaan."""
    # 1. Update SQLite DB (links.db)
    conn = init_sqlite_db(LINKS_DB)
    cursor = conn.cursor()

    for item in data_items:
        cursor.execute("""
            INSERT INTO links (id, url, extracted_embed_url, last_extracted_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                url = excluded.url,
                extracted_embed_url = excluded.extracted_embed_url,
                last_extracted_at = excluded.last_extracted_at
        """, (
            str(item.get("id")),
            item.get("url") or item.get("source_url"),
            item.get("extracted_embed_url"),
            item.get("last_extracted_at")
        ))

    conn.commit()
    conn.close()
    print(f"✅ Data berhasil disimpan ke `{LINKS_DB.name}`")

    # 2. Update JSON File (links.json)
    with open(LINKS_JSON, "w", encoding="utf-8") as f:
        json.dump(data_items, f, indent=2, ensure_ascii=False)
    print(f"✅ Data berhasil disinkronkan ke `{LINKS_JSON.name}`")

def backup_files():
    """Membuat salinan cadangan links_backup.db & links_backup.json di root."""
    if LINKS_DB.exists():
        shutil.copy(LINKS_DB, LINKS_DB_BACKUP)
        print(f"💾 Backup database dibuat: `{LINKS_DB_BACKUP.name}`")

    if LINKS_JSON.exists():
        shutil.copy(LINKS_JSON, LINKS_JSON_BACKUP)
        print(f"💾 Backup JSON dibuat: `{LINKS_JSON_BACKUP.name}`")

def run_extraction(max_workers=8, max_depth=3, timeout=10):
    # Rotasi Backup Sebelum Proses Dijalankan
    backup_files()

    data_items = fetch_data_from_db_or_json()
    if not data_items:
        print("❌ Tidak ada data untuk diproses di `links.db` atau `links.json`.")
        return

    print(f"🚀 Memproses {len(data_items)} items dengan {max_workers} Threads (Max Depth: {max_depth})...")

    session = create_resilient_session()
    updated_results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(process_item, item, session, max_depth, timeout)
            for item in data_items
        ]
        for future in as_completed(futures):
            try:
                res = future.result()
                updated_results.append(res)
            except Exception as exc:
                print(f"⚠️ Thread Exception: {exc}")

    updated_results.sort(key=lambda x: str(x.get("id", "")))

    # Simpan Perubahan ke Database dan JSON
    save_data_to_db_and_json(updated_results)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Root Folder Extractor for links.db & links.json")
    parser.add_argument("--workers", type=int, default=8, help="Jumlah thread pararel (default: 8)")
    parser.add_argument("--depth", type=int, default=3, help="Maksimal kedalaman nested embed (default: 3)")
    parser.add_argument("--timeout", type=int, default=10, help="Timeout HTTP per request (default: 10)")

    args = parser.parse_args()
    run_extraction(max_workers=args.workers, max_depth=args.depth, timeout=args.timeout)
