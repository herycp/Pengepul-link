# 📦 Laporan Integrity Backup & Rollback

_Diperbarui secara otomatis pada: `2026-08-03 17:48:19 UTC`_

## 🗄️ Daftar Backup Database SQLite (`links.db`)

| Nama File Backup | Ukuran File | Tanggal Dibuat |
| :--- | :---: | :---: |
| `db_links.db.backup_20260803_174818` | `28212.0 KB` | `2026-08-03 17:48:18` |
| `db_links.db.backup_20260803_174541` | `28212.0 KB` | `2026-08-03 17:45:38` |
| `db_links.db.backup_20260803_174127` | `28212.0 KB` | `2026-08-03 17:45:37` |
| `db_links.db.backup_20260803_173850` | `28212.0 KB` | `2026-08-03 17:45:37` |
| `db_links.db.backup_20260803_173205` | `28212.0 KB` | `2026-08-03 17:45:37` |

## 📄 Daftar Backup JSON (`links.json`)

| Nama File Backup | Ukuran File | Tanggal Dibuat |
| :--- | :---: | :---: |
| `json_links.json.backup_20260803_174541` | `24864.1 KB` | `2026-08-03 17:45:38` |
| `json_links.json.backup_20260803_173850` | `24879.6 KB` | `2026-08-03 17:45:38` |
| `json_links.json.backup_20260803_172928` | `24895.2 KB` | `2026-08-03 17:45:38` |
| `json_links.json.backup_20260803_172038` | `24910.8 KB` | `2026-08-03 17:45:38` |
| `json_links.json.backup_20260803_171129` | `24926.4 KB` | `2026-08-03 17:45:37` |

## ⏪ Petunjuk Rollback Manual
Untuk mengembalikan database ke versi backup tertentu, jalankan script berikut:
```bash
python check_integrity.py --rollback
```