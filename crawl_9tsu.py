def verify_sitemap_coverage():
    """
    Verifikasi apakah semua URL di setiap sitemap sudah ada di database.
    Jika ada link yang terlewat, reset status sitemap ke pending (offset=0).
    """
    print("\n" + "=" * 60)
    print("🔍 VERIFIKASI KECOCOKAN SITEMAP vs DATABASE")
    print("=" * 60)
    
    sitemap_files = get_sitemap_files()
    if not sitemap_files:
        print("❌ Tidak ada sitemap ditemukan.")
        return 0, 0
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    total_missing = 0
    reset_count = 0
    
    for f in sitemap_files:
        urls = get_urls_from_local_sitemap(f)
        if not urls:
            continue
        
        # Hitung berapa URL di sitemap yang ADA di database
        placeholders = ','.join(['?'] * len(urls))
        query = f"SELECT COUNT(*) FROM links WHERE url IN ({placeholders})"
        cursor.execute(query, urls)
        db_count = cursor.fetchone()[0]
        
        sitemap_count = len(urls)
        missing = sitemap_count - db_count
        
        # Ambil status dari processing_state
        state = get_processing_state(f)
        is_done = state and state['status'] == 'done'
        
        if missing > 0:
            print(f"\n📌 {f}:")
            print(f"   - Total di sitemap: {sitemap_count}")
            print(f"   - Ada di database: {db_count}")
            print(f"   - ❌ Terlewat: {missing} link")
            
            # 🔥 PERBAIKAN: Reset semua sitemap yang memiliki missing, apapun statusnya
            print(f"   - 🔄 Reset status ke 'pending' (offset 0) untuk memproses ulang")
            # Hapus dari processed_sitemaps jika ada
            cursor.execute("DELETE FROM processed_sitemaps WHERE sitemap_file = ?", (f,))
            # Reset processing_state ke pending offset 0
            cursor.execute("""
                INSERT OR REPLACE INTO processing_state (sitemap_file, offset, total, status, updated_at)
                VALUES (?, 0, ?, 'pending', CURRENT_TIMESTAMP)
            """, (f, sitemap_count))
            reset_count += 1
            total_missing += missing
        else:
            if is_done:
                print(f"✅ {f}: {sitemap_count}/{sitemap_count} link terverifikasi (done)")
            else:
                # Jika tidak ada missing, update total jika berbeda
                if state and state['total'] != sitemap_count:
                    cursor.execute("""
                        UPDATE processing_state 
                        SET total = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE sitemap_file = ?
                    """, (sitemap_count, f))
                print(f"✅ {f}: {sitemap_count}/{sitemap_count} link sudah di database")
    
    conn.commit()
    conn.close()
    
    print("\n" + "=" * 60)
    if total_missing == 0:
        print("✅ SEMUA SITEMAP TERVERIFIKASI - Tidak ada link terlewat")
    else:
        print(f"⚠️ Ditemukan {total_missing} link terlewat di {reset_count} sitemap")
        print(f"🔄 {reset_count} sitemap direset ke status 'pending' (offset=0)")
    print("=" * 60)
    
    return total_missing, reset_count
