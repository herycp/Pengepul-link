# 📦 Laporan Integrity Backup & Rollback

_Diperbarui secara otomatis pada: `2026-08-03 17:23:22 UTC`_

## 🗄️ Daftar Backup Database SQLite (`links.db`)

| Nama File Backup | Ukuran File | Tanggal Dibuat |
| :--- | :---: | :---: |
| `db_links.db.backup_20260803_172320` | `28212.0 KB` | `2026-08-03 17:23:20` |
| `db_links.db.backup_20260803_172038` | `28212.0 KB` | `2026-08-03 17:20:34` |
| `db_links.db.backup_20260803_171405` | `28212.0 KB` | `2026-08-03 17:20:33` |
| `db_links.db.backup_20260803_171129` | `28212.0 KB` | `2026-08-03 17:20:33` |
| `db_links.db.backup_20260803_165927` | `28212.0 KB` | `2026-08-03 17:20:33` |

## 📄 Daftar Backup JSON (`links.json`)

| Nama File Backup | Ukuran File | Tanggal Dibuat |
| :--- | :---: | :---: |
| `json_links.json.backup_20260803_172038` | `24910.8 KB` | `2026-08-03 17:20:34` |
| `json_links.json.backup_20260803_171129` | `24926.4 KB` | `2026-08-03 17:20:34` |
| `json_links.json.backup_20260803_165651` | `24942.0 KB` | `2026-08-03 17:20:34` |
| `json_links.json.backup_20260803_164429` | `24957.7 KB` | `2026-08-03 17:20:34` |
| `json_links.json.backup_20260803_163300` | `24973.3 KB` | `2026-08-03 17:20:34` |

## ⏪ Petunjuk Rollback Manual
Untuk mengembalikan database ke versi backup tertentu, jalankan script berikut:
```bash
python check_integrity.py --rollback
```