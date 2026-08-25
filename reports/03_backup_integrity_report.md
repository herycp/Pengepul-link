# 📦 Laporan Integrity Backup & Rollback

_Diperbarui secara otomatis pada: `2026-08-25 06:50:01 UTC`_

## 🗄️ Daftar Backup Database SQLite (`links.db`)

| Nama File Backup | Ukuran File | Tanggal Dibuat |
| :--- | :---: | :---: |
| `db_links.db.backup_20260803_175714` | `28212.0 KB` | `2026-08-25 06:49:57` |
| `db_links.db.backup_20260803_175557` | `28212.0 KB` | `2026-08-25 06:49:57` |
| `db_links.db.backup_20260803_175326` | `28212.0 KB` | `2026-08-25 06:49:57` |
| `db_links.db.backup_20260803_175047` | `28212.0 KB` | `2026-08-25 06:49:57` |
| `db_links.db.backup_20260803_174818` | `28212.0 KB` | `2026-08-25 06:49:57` |

## 📄 Daftar Backup JSON (`links.json`)

| Nama File Backup | Ukuran File | Tanggal Dibuat |
| :--- | :---: | :---: |
| `json_links.json.backup_20260803_175557` | `24833.0 KB` | `2026-08-25 06:49:57` |
| `json_links.json.backup_20260803_175047` | `24848.5 KB` | `2026-08-25 06:49:57` |
| `json_links.json.backup_20260803_174541` | `24864.1 KB` | `2026-08-25 06:49:57` |
| `json_links.json.backup_20260803_173850` | `24879.6 KB` | `2026-08-25 06:49:57` |
| `json_links.json.backup_20260803_172928` | `24895.2 KB` | `2026-08-25 06:49:57` |

## ⏪ Petunjuk Rollback Manual
Untuk mengembalikan database ke versi backup tertentu, jalankan script berikut:
```bash
python check_integrity.py --rollback
```