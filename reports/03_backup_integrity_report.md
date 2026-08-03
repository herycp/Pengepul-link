# 📦 Laporan Integrity Backup & Rollback

_Diperbarui secara otomatis pada: `2026-08-03 16:59:29 UTC`_

## 🗄️ Daftar Backup Database SQLite (`links.db`)

| Nama File Backup | Ukuran File | Tanggal Dibuat |
| :--- | :---: | :---: |
| `db_links.db.backup_20260803_165927` | `28212.0 KB` | `2026-08-03 16:59:27` |
| `db_links.db.backup_20260803_165651` | `28212.0 KB` | `2026-08-03 16:56:48` |
| `db_links.db.backup_20260803_164704` | `28212.0 KB` | `2026-08-03 16:56:47` |
| `db_links.db.backup_20260803_164429` | `28212.0 KB` | `2026-08-03 16:56:47` |
| `db_links.db.backup_20260803_163536` | `28212.0 KB` | `2026-08-03 16:56:47` |

## 📄 Daftar Backup JSON (`links.json`)

| Nama File Backup | Ukuran File | Tanggal Dibuat |
| :--- | :---: | :---: |
| `json_links.json.backup_20260803_165651` | `24942.0 KB` | `2026-08-03 16:56:48` |
| `json_links.json.backup_20260803_164429` | `24957.7 KB` | `2026-08-03 16:56:47` |
| `json_links.json.backup_20260803_163300` | `24973.3 KB` | `2026-08-03 16:56:47` |
| `json_links.json.backup_20260803_161734` | `24988.9 KB` | `2026-08-03 16:56:47` |

## ⏪ Petunjuk Rollback Manual
Untuk mengembalikan database ke versi backup tertentu, jalankan script berikut:
```bash
python check_integrity.py --rollback
```