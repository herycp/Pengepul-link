# 📦 Laporan Integrity Backup & Rollback

_Diperbarui secara otomatis pada: `2026-08-03 17:53:27 UTC`_

## 🗄️ Daftar Backup Database SQLite (`links.db`)

| Nama File Backup | Ukuran File | Tanggal Dibuat |
| :--- | :---: | :---: |
| `db_links.db.backup_20260803_175326` | `28212.0 KB` | `2026-08-03 17:53:26` |
| `db_links.db.backup_20260803_175047` | `28212.0 KB` | `2026-08-03 17:50:39` |
| `db_links.db.backup_20260803_174818` | `28212.0 KB` | `2026-08-03 17:50:39` |
| `db_links.db.backup_20260803_174541` | `28212.0 KB` | `2026-08-03 17:50:39` |
| `db_links.db.backup_20260803_174127` | `28212.0 KB` | `2026-08-03 17:50:39` |

## 📄 Daftar Backup JSON (`links.json`)

| Nama File Backup | Ukuran File | Tanggal Dibuat |
| :--- | :---: | :---: |
| `json_links.json.backup_20260803_175047` | `24848.5 KB` | `2026-08-03 17:50:39` |
| `json_links.json.backup_20260803_174541` | `24864.1 KB` | `2026-08-03 17:50:39` |
| `json_links.json.backup_20260803_173850` | `24879.6 KB` | `2026-08-03 17:50:39` |
| `json_links.json.backup_20260803_172928` | `24895.2 KB` | `2026-08-03 17:50:39` |
| `json_links.json.backup_20260803_172038` | `24910.8 KB` | `2026-08-03 17:50:39` |

## ⏪ Petunjuk Rollback Manual
Untuk mengembalikan database ke versi backup tertentu, jalankan script berikut:
```bash
python check_integrity.py --rollback
```