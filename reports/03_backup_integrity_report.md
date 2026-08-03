# 📦 Laporan Integrity Backup & Rollback

_Diperbarui secara otomatis pada: `2026-08-03 16:47:06 UTC`_

## 🗄️ Daftar Backup Database SQLite (`links.db`)

| Nama File Backup | Ukuran File | Tanggal Dibuat |
| :--- | :---: | :---: |
| `db_links.db.backup_20260803_164704` | `28212.0 KB` | `2026-08-03 16:47:04` |
| `db_links.db.backup_20260803_164429` | `28212.0 KB` | `2026-08-03 16:44:22` |
| `db_links.db.backup_20260803_163536` | `28212.0 KB` | `2026-08-03 16:44:22` |
| `db_links.db.backup_20260803_163300` | `28212.0 KB` | `2026-08-03 16:44:22` |
| `db_links.db.backup_20260803_162007` | `28212.0 KB` | `2026-08-03 16:44:22` |

## 📄 Daftar Backup JSON (`links.json`)

| Nama File Backup | Ukuran File | Tanggal Dibuat |
| :--- | :---: | :---: |
| `json_links.json.backup_20260803_164429` | `24957.7 KB` | `2026-08-03 16:44:22` |
| `json_links.json.backup_20260803_163300` | `24973.3 KB` | `2026-08-03 16:44:22` |
| `json_links.json.backup_20260803_161734` | `24988.9 KB` | `2026-08-03 16:44:22` |

## ⏪ Petunjuk Rollback Manual
Untuk mengembalikan database ke versi backup tertentu, jalankan script berikut:
```bash
python check_integrity.py --rollback
```