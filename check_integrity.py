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

# ============================================================
# REPORT 1: CEK PENGGANTIAN URL EMBED (01_embed_replacement_report.md)
# ============================================================
def generate_embed_report(target_domain="blogspherenews.xyz", limit=20):
    ensure_reports_dir()
    filepath = os.path.join(REPORTS_DIR, "01_embed_replacement_report.md")

    if not os.path.exists(DB_FILE):
        content = "# ❌ Error\nFile `links.db` tidak ditemukan."
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
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

    md.append("## 📋 Detail Perubahan Embed (Sampel Terkini)\n")
    if updated_rows:
        md.append("| ID | Halaman Asli / Section | Real Embed Target Baru | Platform |")
        md.append("| :---: | :--- | :--- | :---: |")
        for row in updated_rows[:limit]:
            rec_id = row[0]
            page_url = f"[{row[1][:30]}...]({row[1]})" if row[1] else "-"
            embed_url = f"`{row[2]}`" if row[2] else "-"
            platform = f"`{row[3]}`" if row[3] else "-"
            md.append(f"| {rec_id} | {page_url} | {embed_url} | {platform} |")
    else:
        md.append("> ⚠️ **Perhatian**: Belum ada record embed yang berhasil diperbarui.")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"📄 Report 1 dibuat: `{filepath}`")

# ============================================================
# REPORT 2: CEK SINKRONISASI DB & JSON (02_db_json_sync_report.md)
# ============================================================
def generate_sync_report():
    ensure_reports_dir()
    filepath = os.path.join(REPORTS_DIR, "02_db_json_sync_report.md")

    db_exists = os.path.exists(DB_FILE)
    json_exists = os.path.exists(JSON_FILE)

    db_count = 0
    json_count = 0

    if db_exists:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM links")
        db_count = cursor.fetchone()[0]
        conn.close()

    if json_exists:
        try:
            with open(JSON_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                json_count = len(data.get('links', []))
        except Exception:
            json_count = -1

    is_synced = (db_count == json_count) and db_count > 0
    status_badge = "✅ **SINKRON**" if is_synced else "❌ **TIDAK SINKRON**"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

    md = []
    md.append("# 🔄 Laporan Sinkronisasi DB & JSON\n")
    md.append(f"_Diperbarui secara otomatis pada: `{now}`_\n")
    md.append("## 📌 Status Sinkronisasi\n")
    md.append(f"**Status Saat Ini:** {status_badge}\n")
    md.append("| File Data | Format | Jumlah Record | Status File |")
    md.append("| :--- | :---: | :---: | :---: |")
    md.append(f"| `links.db` | SQLite | `{db_count}` | {'Ada' if db_exists else 'TIDAK ADA'} |")
    md.append(f"| `links.json` | JSON | `{json_count}` | {'Ada' if json_exists else 'TIDAK ADA'} |\n")

    if not is_synced:
        md.append("### ⚠️ Catatan Ketidaksinkronan")
        md.append(f"Terdapat selisih **{abs(db_count - json_count)} record** antara SQLite DB dan file JSON.")
        md.append("Jalankan perintah berikut untuk menyinkronkan ulang secara manual:")
        md.append("```bash\npython check_integrity.py --sync-db-to-json\n```")
    else:
        md.append("> ✨ **Info**: Jumlah data di database SQLite (`links.db`) dan file JSON (`links.json`) cocok 100%.")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"📄 Report 2 dibuat: `{filepath}`")

# ============================================================
# REPORT 3: BACKUP & ROLLBACK STATUS (03_backup_integrity_report.md)
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
    else:
        generate_all_reports()
          
