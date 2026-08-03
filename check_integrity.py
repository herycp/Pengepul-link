import sqlite3
import json
import os
import shutil
import glob
from datetime import datetime

DB_FILE = "links.db"
JSON_FILE = "links.json"
BACKUP_DIR = "backups"
REPORTS_DIR = "reports"

def ensure_reports_dir():
    if not os.path.exists(REPORTS_DIR):
        os.makedirs(REPORTS_DIR)

def get_old_embeds_from_backup():
    """Mengambil mapping embed_url lama dari file backup database paling baru."""
    old_embeds = {}
    if not os.path.exists(BACKUP_DIR):
        return old_embeds

    db_backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "db_*.backup_*")), key=os.path.getmtime, reverse=True)
    if not db_backups:
        return old_embeds

    latest_backup = db_backups[0]
    try:
        conn = sqlite3.connect(latest_backup)
        cursor = conn.cursor()
        cursor.execute("SELECT id, embed_url FROM links")
        for row in cursor.fetchall():
            old_embeds[row[0]] = row[1]
        conn.close()
    except Exception as e:
        print(f"⚠️ Gagal membaca backup DB untuk nilai lama: {e}")

    return old_embeds

# ============================================================
# REPORT 1: CEK PENGGANTIAN URL EMBED (Lama vs Baru)
# ============================================================
def generate_embed_report(target_domain="blogspherenews.xyz", limit=20):
    ensure_reports_dir()
    filepath = os.path.join(REPORTS_DIR, "01_embed_replacement_report.md")

    if not os.path.exists(DB_FILE):
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("# ❌ Error\nFile `links.db` tidak ditemukan.")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM links")
    total_records = cursor.fetchone()[0]

    # Record yang SUDAH diganti
    cursor.execute("SELECT id, url, embed_url, embed_platform FROM links WHERE embed_url NOT LIKE ?", (f'%{target_domain}%',))
    updated_rows = cursor.fetchall()

    # Record yang BELUM diganti
    cursor.execute("SELECT COUNT(*) FROM links WHERE embed_url LIKE ?", (f'%{target_domain}%',))
    remaining_count = cursor.fetchone()[0]

    conn.close()

    # Mengambil embed URL lama dari backup DB
    old_embeds_map = get_old_embeds_from_backup()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    pct_success = round((len(updated_rows) / total_records * 100), 2) if total_records > 0 else 0

    md = []
    md.append("# 📊 Laporan Penggantian URL Embed\n")
    md.append(f"_Diperbarui secara otomatis pada: `{now}`_\n")
    md.append("## 📈 Ringkasan Ekstraksi\n")
    md.append("| Metrik | Jumlah | Persentase |")
    md.append("| :--- | :---: | :---: |")
    md.append(f"| **Total Record DB** | `{total_records}` | `100%` |")
    md.append(f"| **Berhasil Diperbarui** | `{len(updated_rows)}` | `{pct_success}%` |")
    md.append(f"| **Belum Diperbarui** | `{remaining_count}` | `{round(100 - pct_success, 2)}%` |\n")

    md.append("## 📋 Detail Perbandingan Embed (Nilai Lama vs Baru)\n")
    if updated_rows:
        md.append("| ID | Halaman Asli / Section | Embed Lama (`blogspherenews`) | Real Embed Baru | Platform Baru |")
        md.append("| :---: | :--- | :--- | :--- | :---: |")
        for row in updated_rows[:limit]:
            rec_id = row[0]
            page_url = f"[{row[1][:25]}...]({row[1]})" if row[1] else "-"
            
            # Embed lama dari backup
            old_val = old_embeds_map.get(rec_id, f"*(Sebelumnya {target_domain})*")
            old_embed_display = f"`{old_val}`" if old_val else "-"
            
            new_embed_display = f"`{row[2]}`" if row[2] else "-"
            platform_display = f"`{row[3]}`" if row[3] else "-"
            
            md.append(f"| {rec_id} | {page_url} | {old_embed_display} | {new_embed_display} | {platform_display} |")
    else:
        md.append("> ⚠️ **Perhatian**: Belum ada record embed yang berhasil diperbarui.")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"📄 Report 1 dibuat: `{filepath}`")

# ============================================================
# REPORT 2: CEK SINKRONISASI ISI DB & JSON (Content Match Query)
# ============================================================
def generate_sync_report():
    ensure_reports_dir()
    filepath = os.path.join(REPORTS_DIR, "02_db_json_sync_report.md")

    db_exists = os.path.exists(DB_FILE)
    json_exists = os.path.exists(JSON_FILE)

    db_records = {}
    json_records = {}
    mismatches = []
    missing_in_json = []
    missing_in_db = []

    # 1. Baca isi Database SQLite
    if db_exists:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('SELECT url, title, season, episode, image, description, embed_url, embed_platform FROM links')
        for row in cursor.fetchall():
            url = row[0]
            db_records[url] = {
                'url': row[0],
                'title': row[1] or "",
                'season': str(row[2]) if row[2] is not None else "",
                'episode': str(row[3]) if row[3] is not None else "",
                'image': row[4] or "",
                'description': row[5] or "",
                'embed_url': row[6] or "",
                'embed_platform': row[7] or ""
            }
        conn.close()

    # 2. Baca isi File JSON
    if json_exists:
        try:
            with open(JSON_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                json_links = data.get('links', [])
                for item in json_links:
                    url = item.get('url')
                    if url:
                        json_records[url] = {
                            'url': item.get('url', ''),
                            'title': item.get('title') or "",
                            'season': str(item.get('season')) if item.get('season') is not None else "",
                            'episode': str(item.get('episode')) if item.get('episode') is not None else "",
                            'image': item.get('image') or "",
                            'description': item.get('description') or "",
                            'embed_url': item.get('embed_url') or "",
                            'embed_platform': item.get('embed_platform') or ""
                        }
        except Exception as e:
            print(f"⚠️ Gagal membaca JSON: {e}")

    # 3. Bandingkan Isi Data per Record
    all_urls = set(db_records.keys()).union(set(json_records.keys()))
    
    for url in all_urls:
        db_item = db_records.get(url)
        json_item = json_records.get(url)

        if not db_item:
            missing_in_db.append(url)
            continue
        if not json_item:
            missing_in_json.append(url)
            continue

        # Cek perbedaan isi kolom demi kolom
        diff_fields = []
        for field in ['title', 'season', 'episode', 'embed_url', 'embed_platform']:
            val_db = db_item[field]
            val_json = json_item[field]
            if val_db != val_json:
                diff_fields.append({
                    'field': field,
                    'db_val': val_db,
                    'json_val': val_json
                })

        if diff_fields:
            mismatches.append({
                'url': url,
                'diffs': diff_fields
            })

    db_count = len(db_records)
    json_count = len(json_records)
    is_count_synced = (db_count == json_count) and db_count > 0
    is_content_synced = (len(mismatches) == 0 and len(missing_in_json) == 0 and len(missing_in_db) == 0)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

    md = []
    md.append("# 🔄 Laporan Content Sync DB vs JSON\n")
    md.append(f"_Diperbarui secara otomatis pada: `{now}`_\n")
    
    if is_content_synced and is_count_synced:
        status_badge = "✅ **100% SINKRON (Jumlah & Isi Identik)**"
    else:
        status_badge = "❌ **TIDAK SINKRON (Terdapat Perbedaan Data)**"

    md.append("## 📌 Status Perbandingan Konten\n")
    md.append(f"**Status Keseluruhan:** {status_badge}\n")
    md.append("| Indikator Pengecekan | Database (`links.db`) | JSON (`links.json`) | Status Perbandingan |")
    md.append("| :--- | :---: | :---: | :---: |")
    md.append(f"| **Jumlah Total Record** | `{db_count}` | `{json_count}` | {'✅ Jumlah Cocok' if is_count_synced else '❌ Beda Jumlah'} |")
    md.append(f"| **Perbedaan Isi Field** | `{len(mismatches)}` beda | `{len(mismatches)}` beda | {'✅ Isi Identik' if len(mismatches) == 0 else '❌ Ada Perbedaan Isi'} |")
    md.append(f"| **Hilang di JSON** | - | `{len(missing_in_json)}` record | {'✅ Tidak ada' if len(missing_in_json) == 0 else '⚠️ Ada Data Hilang'} |")
    md.append(f"| **Hilang di DB** | `{len(missing_in_db)}` record | - | {'✅ Tidak ada' if len(missing_in_db) == 0 else '⚠️ Ada Data Hilang'} |\n")

    if mismatches:
        md.append("## ⚠️ Detail Perbedaan Isi Record (DB vs JSON)\n")
        md.append("| URL Target | Kolom / Field | Nilai di DB (`links.db`) | Nilai di JSON (`links.json`) |")
        md.append("| :--- | :---: | :--- | :--- |")
        for m in mismatches[:15]:
            url_disp = f"[{m['url'][:25]}...]({m['url']})"
            for diff in m['diffs']:
                f_name = f"`{diff['field']}`"
                db_v = f"`{diff['db_val'][:30]}`" if diff['db_val'] else "*(kosong)*"
                json_v = f"`{diff['json_val'][:30]}`" if diff['json_val'] else "*(kosong)*"
                md.append(f"| {url_disp} | {f_name} | {db_v} | {json_v} |")
        
        if len(mismatches) > 15:
            md.append(f"\n_...dan {len(mismatches) - 15} perbedaan lainnya._\n")

    if not is_content_synced:
        md.append("\n### 💡 Solusi Penyelarasan")
        md.append("Jalankan perintah berikut untuk mengekspor ulang SQLite DB ke JSON:")
        md.append("```bash\npython check_integrity.py --sync-db-to-json\n```")
    else:
        md.append("\n> ✨ **Info**: Seluruh isi kolom (`embed_url`, `embed_platform`, `title`, `season`, `episode`) pada SQLite Database dan file JSON cocok dan identik 100%.")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"📄 Report 2 dibuat: `{filepath}`")

# ============================================================
# REPORT 3: BACKUP & ROLLBACK STATUS
# ============================================================
def generate_backup_report():
    ensure_reports_dir()
    filepath = os.path.join(REPORTS_DIR, "03_backup_integrity_report.md")

    db_backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "db_*.backup_*")), key=os.path.getmtime, reverse=True)
    json_backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "json_*.backup_*")), key=os.path.getmtime, reverse=True)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

    md = []
    md.append("# 📦 Laporan Integrity Backup & Rollback\n")
    md.append(f"_Diperbarui secara otomatis pada: `{now}`_\n")
    md.append("## 🗄️ Daftar Backup Database SQLite (`links.db`)\n")

    if db_backups:
        md.append("| Nama File Backup | Ukuran File | Tanggal Dibuat |")
        md.append("| :--- | :---: | :---: |")
        for f in db_backups:
            fname = os.path.basename(f)
            size = f"{os.path.getsize(f) / 1024:.1f} KB"
            mtime = datetime.fromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d %H:%M:%S")
            md.append(f"| `{fname}` | `{size}` | `{mtime}` |")
    else:
        md.append("> ⚠️ Tidak ada file backup database ditemukan.")

    md.append("\n## 📄 Daftar Backup JSON (`links.json`)\n")
    if json_backups:
        md.append("| Nama File Backup | Ukuran File | Tanggal Dibuat |")
        md.append("| :--- | :---: | :---: |")
        for f in json_backups:
            fname = os.path.basename(f)
            size = f"{os.path.getsize(f) / 1024:.1f} KB"
            mtime = datetime.fromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d %H:%M:%S")
            md.append(f"| `{fname}` | `{size}` | `{mtime}` |")
    else:
        md.append("> ⚠️ Tidak ada file backup JSON ditemukan.")

    md.append("\n## ⏪ Petunjuk Rollback Manual")
    md.append("Untuk mengembalikan database ke versi backup tertentu, jalankan script berikut:")
    md.append("```bash\npython check_integrity.py --rollback\n```")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"📄 Report 3 dibuat: `{filepath}`")

# ============================================================
# UTILS & SINKRONISASI
# ============================================================
def sync_db_to_json():
    if not os.path.exists(DB_FILE):
        return
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('SELECT url, title, season, episode, image, description, embed_url, embed_platform, created_at FROM links')
    rows = cursor.fetchall()
    conn.close()

    links = []
    for row in rows:
        links.append({
            'url': row[0], 'title': row[1], 'season': row[2], 'episode': row[3],
            'image': row[4], 'description': row[5], 'embed_url': row[6],
            'embed_platform': row[7], 'created_at': row[8]
        })

    output = {'timestamp': datetime.now().isoformat(), 'total': len(links), 'links': links}
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"🔄 Berhasil menyinkronkan `{JSON_FILE}` dari Database!")

def rollback_database():
    if not os.path.exists(BACKUP_DIR):
        print(f"❌ Folder {BACKUP_DIR} tidak ditemukan!")
        return

    db_backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "db_*.backup_*")), key=os.path.getmtime, reverse=True)
    if not db_backups:
        print("❌ Tidak ada file backup database ditemukan.")
        return

    target_backup = db_backups[0]
    shutil.copy2(target_backup, DB_FILE)
    print(f"✅ Database direstore dari backup terbaru: `{target_backup}`")
    sync_db_to_json()

def generate_all_reports():
    generate_embed_report()
    generate_sync_report()
    generate_backup_report()

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == '--sync-db-to-json':
            sync_db_to_json()
        elif arg == '--generate-reports':
            generate_all_reports()
        elif arg == '--rollback':
            rollback_database()
    else:
        generate_all_reports()
