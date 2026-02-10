#!/usr/bin/env python3
"""
Reset Customer Database - Clears all customer and vehicle data.

Usage:
  python reset_customer_db.py
  
This will:
  - Delete the SQLite database file
  - Clear all customer records
  - Clear all vehicle records
  - Clear all VIN associations
  
The database will be recreated empty on next bot startup.
"""

import os
import sys
from config import DATA_FOLDER

DB_PATH = os.path.join(DATA_FOLDER, "customers.db")

def reset_database():
    print("\n" + "=" * 60)
    print("🗑️  RESET CUSTOMER DATABASE")
    print("=" * 60 + "\n")
    
    if not os.path.exists(DB_PATH):
        print(f"✅ Database doesn't exist yet: {DB_PATH}")
        print("   Nothing to reset!")
        return
    
    print(f"📍 Database location: {DB_PATH}")
    print("\n⚠️  WARNING: This will DELETE ALL customer data:")
    print("   - All customer records")
    print("   - All vehicle records") 
    print("   - All VIN associations")
    print("   - All Telegram ID links")
    print("\n   This CANNOT be undone!")
    
    confirm = input("\n❓ Type 'DELETE' to confirm: ").strip()
    
    if confirm != "DELETE":
        print("\n❌ Reset cancelled. Database unchanged.")
        return
    
    try:
        os.remove(DB_PATH)
        print(f"\n✅ Database deleted: {DB_PATH}")
        print("   The database will be recreated empty on next bot startup.")
        print("\n💡 Note: This does NOT delete:")
        print("   - CSV service records in /data folder")
        print("   - Carfax PDFs or ingested Carfax data in Pinecone")
        print("   - Owner's manuals in Pinecone")
        print("   - Appointment backups in appointments.json")
        
    except Exception as e:
        print(f"\n❌ Error deleting database: {e}")
        sys.exit(1)


if __name__ == "__main__":
    reset_database()
