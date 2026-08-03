import sqlite3
import json
import os
import shutil
from datetime import datetime

DB_FILE = "links.db"
JSON_FILE = "links.json"

def backup_file(filename):
    """Buat backup file dengan timestamp"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"{filename}.backup_clean_{timestamp}"
    if os.path.exists(filename):
        shutil.copy2(filename, backup_name)
        print(f"📦 Backup dibuat: {backup_name}")
        return backup_name
    print(f"⚠️ File {filename} tidak ditemukan, backup skip")
    return None

def clean_database():
    """Hapus semua record dengan embed_url IS NULL"""
    if not os.path.exists(DB_FILE):
        print(f"⚠️ File {DB_FILE} tidak ditemukan, lewati database")
        return 0
    
    # Backup dulu
    backup_file(DB_FILE)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Hitung record yang akan dihapus
    cursor.execute("SELECT COUNT(*) FROM links WHERE embed_url IS NULL OR embed_url = ''")
    total = cursor.fetchone()[0]
    print(f"🔍 Ditemukan {total} record dengan embed_url NULL/empty")
    
    if total == 0:
        print("✅ Tidak ada data yang perlu dibersihkan")
        conn.close()
        return 0
    
    # Hapus record
    cursor.execute("DELETE FROM links WHERE embed_url IS NULL OR embed_url = ''")
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    
    print(f"🗑️  {deleted} record dihapus dari database")
    return deleted

def clean_json():
    """Hapus semua link dengan embed_url null di JSON"""
    if not os.path.exists(JSON_FILE):
        print(f"⚠️ File {JSON_FILE} tidak ditemukan, lewati JSON")
        return 0
    
    # Backup JSON
    backup_file(JSON_FILE)
    
    with open(JSON_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    original_count = len(data.get('links', []))
    
    # Filter: hanya simpan link yang memiliki embed_url valid
    cleaned_links = [
        link for link in data.get('links', [])
        if link.get('embed_url') not in [None, '', 'null']
    ]
    
    removed = original_count - len(cleaned_links)
    
    if removed == 0:
        print("✅ Tidak ada perubahan di JSON")
        return 0
    
    # Update data
    data['links'] = cleaned_links
    data['total'] = len(cleaned_links)
    data['timestamp'] = datetime.now().isoformat()
    
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"🗑️  {removed} link dihapus dari JSON")
    return removed

def main():
    print("=" * 60)
    print("🧹 CLEAN NULL EMBED_URL")
    print("=" * 60)
    
    db_deleted = clean_database()
    json_removed = clean_json()
    
    print("\n" + "=" * 60)
    print(f"✅ Selesai!")
    print(f"   - Database: {db_deleted} record dihapus")
    print(f"   - JSON: {json_removed} link dihapus")
    print("=" * 60)

if __name__ == "__main__":
    main()
