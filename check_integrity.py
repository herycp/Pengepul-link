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
# LOGIKA KHUSUS: AMBIL 100 DATA DARI BACKUP TERBARU vs DB SEKARANG
# ============================================================
def get_100_embed_comparisons(target_domain="blogspherenews.xyz", limit=100):
    comparison_list = []
    if not os.path.exists(BACKUP_DIR):
        print(f"⚠️ Folder {BACKUP_DIR} tidak ditemukan.")
        return comparison_list

    # 1. Ambil file backup DB TERBARU (reverse=True -> index 0 adalah paling baru)
    db_backups = sorted(glob.glob(os.path.join(BACKUP_DIR, "db_*.backup_*")), key=os.path.getmtime, reverse=True)

    if not db_backups:
        print("⚠️ Tidak ada file backup DB ditemukan.")
        return comparison_list

    latest_backup = db_backups[0]
    old_records = []

    try:
        conn_old = sqlite3.connect(latest_backup)
        cursor_old = conn_old.cursor()
        # Ambil 100 record pertama dari BACKUP TERBARU yang berisikan blogspherenews.xyz
        cursor_old.execute(
            "SELECT id, url, embed_url FROM links WHERE embed_url LIKE ? ORDER BY id ASC LIMIT ?",
            (f'%{target_domain}%', limit)
        )
        old_records = cursor_old.fetchall()
        conn_old.close()
        print(f"🔍 Mengambil {len(old_records)} data `{target_domain}` dari backup terbaru: {os.path.basename(latest_backup)}")
    except Exception as e:
        print(f"⚠️ Gagal membaca backup terbaru {latest_backup}: {e}")

    if not old_records or not os.path.exists(DB_FILE):
        return comparison_list

    # 2. Buka DB SEKARANG (links.db) dan ambil nilai terbarunya berdasarkan ID atau URL
    conn_curr = sqlite3.connect(DB_FILE)
    cursor_curr = conn_curr.cursor()

    for rec_id, page_url, old_embed in old_records:
        cursor_curr.execute(
            "SELECT embed_url, embed_platform FROM links WHERE id = ? OR url = ?",
            (rec_id, page_url)
        )
        curr_row = cursor_curr.fetchone()

        new_embed = curr_row[0] if curr_row else "-"
        platform = curr_row[1] if curr_row and curr_row[1] else "-"

        comparison_list.append({
            'id': rec_id,
            'page_url': page_url,
            'old_embed': old_embed,
            'new_embed': new_embed,
            'platform': platform
        })

    conn_curr.close()
    return comparison_list

# ============================================================
# REPORT 1: PENGGANTIAN URL EMBED (100 ENTRI BACKUP TERBARU vs DB SEKARANG)
# ============================================================
def generate_embed_report(target_domain="blogspherenews.xyz", limit=100):
    ensure_reports_dir()
    filepath = os.path.join(REPORTS_DIR, "01_embed_replacement_report.md")

    if not os.path.exists(DB_FILE):
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("# ❌ Error\nFile `links.db` tidak ditemukan.")
        return

    # Ringkasan statistik DB Sekarang
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM links")
    total_records = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM links WHERE embed_url NOT LIKE ?", (f'%{target_domain}%',))
    updated_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM links WHERE embed_url LIKE ?", (f'%{target_domain}%',))
    remaining_count = cursor.fetchone()[0]
    conn.close()

    pct_success = round((updated_count / total_records * 100), 2) if total_records > 0 else 0
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

    # Ambil 100 entri perbandingan dari BACKUP TERBARU
    comparisons = get_100_embed_comparisons(target_domain, limit)

    md = []
    md.append("# 📊 Laporan Penggantian URL Embed\n")
    md.append(f"_Diperbarui secara otomatis pada: `{now}`_\n")
    md.append("## 📈 Ringkasan Ekstraksi Real-time\n")
    md.append("| Metrik | Jumlah | Persentase |")
    md.append("| :--- | :---: | :---: |")
    md.append(f"| **Total Record DB** | `{total_records}` | `100%` |")
    md.append(f"| **Berhasil Diperbarui** | `{updated_count}` | `{pct_success}%` |")
    md.append(f"| **Belum Diperbarui** | `{remaining_count}` | `{round(100 - pct_success, 2)}%` |\n")

    md.append(f"## 📋 Perbandingan {len(comparisons)} Entri Pertama (Backup Terbaru vs DB Sekarang)\n")
    if comparisons:
        md.append("| ID | Halaman Asli / Section | Embed Lama (`blogspherenews` dari Backup) | Real Embed Baru (`links.db` Sekarang) | Platform Baru | Status |")
        md.append("| :---: | :--- | :--- | :--- | :---: | :---: |")

        for item in comparisons:
            rec_id = item['id']
            page_url = f"[{item['page_url'][:25]}...]({item['page_url']})" if item['page_url'] else "-"
            old_embed = f"`{item['old_embed']}`"
            new_embed = f"`{item['new_embed']}`"
            platform = f"`{item['platform']}`"
            
            # Status: jika nilai di DB sekarang sudah TIDAK mengandung blogspherenews
            is_updated = target_domain not in item['new_embed'] and item['new_embed'] != "-"
            status = "✅ Diperbarui" if is_updated else "⏳ Belum"

            md.append(f"| {rec_id} | {page_url} | {old_embed} | {new_embed} | {platform} | {status} |")
    else:
        md.append("> ⚠️ **Perhatian**: Tidak ditemukan entri `blogspherenews.xyz` pada file backup terbaru.")

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"📄 Report 1 berhasil diperbarui: `{filepath}` ({len(comparisons)} entri dibandingkan)")
