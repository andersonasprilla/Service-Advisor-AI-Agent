#!/usr/bin/env python3
"""
Full System Reset - Nuclear option to start completely fresh.

Usage:
  python full_reset.py
  
This will DELETE:
  ✓ Customer database (SQLite)
  ✓ Appointment history (appointments.json)
  ✓ All Carfax data from Pinecone
  ✓ In-memory session data (when bot restarts)

This will KEEP:
  ✓ Owner's manuals in Pinecone (civic-2025, ridgeline-2025, passport-2026)
  ✓ CSV service records in /data folder
  ✓ Configuration (.env file)
"""

import os
import sys
from config import DATA_FOLDER, APPOINTMENTS_FILE
from services.clients import get_pinecone_index

DB_PATH = os.path.join(DATA_FOLDER, "customers.db")

def confirm_action(message):
    """Ask for confirmation."""
    response = input(f"\n{message} (yes/no): ").strip().lower()
    return response in ["yes", "y"]

def reset_customer_database():
    """Delete the SQLite customer database."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"   ✅ Deleted customer database: {DB_PATH}")
    else:
        print(f"   ℹ️  No customer database found")

def reset_appointments():
    """Delete appointment history."""
    if os.path.exists(APPOINTMENTS_FILE):
        os.remove(APPOINTMENTS_FILE)
        print(f"   ✅ Deleted appointments: {APPOINTMENTS_FILE}")
    else:
        print(f"   ℹ️  No appointments file found")

def list_carfax_namespaces():
    """List all Carfax namespaces in Pinecone."""
    try:
        index = get_pinecone_index()
        stats = index.describe_index_stats()
        
        carfax_namespaces = [
            ns for ns in stats.namespaces.keys() 
            if ns.startswith("carfax-")
        ]
        
        return carfax_namespaces
    except Exception as e:
        print(f"   ⚠️  Error listing Pinecone namespaces: {e}")
        return []

def delete_carfax_data():
    """Delete all Carfax data from Pinecone."""
    namespaces = list_carfax_namespaces()
    
    if not namespaces:
        print(f"   ℹ️  No Carfax data found in Pinecone")
        return
    
    print(f"\n   Found {len(namespaces)} Carfax namespaces:")
    for ns in namespaces:
        print(f"      - {ns}")
    
    if not confirm_action("   Delete all Carfax data from Pinecone?"):
        print("   ⏭️  Skipped Carfax deletion")
        return
    
    try:
        index = get_pinecone_index()
        for ns in namespaces:
            index.delete(delete_all=True, namespace=ns)
            print(f"   ✅ Deleted namespace: {ns}")
    except Exception as e:
        print(f"   ❌ Error deleting Carfax data: {e}")

def full_reset():
    print("\n" + "=" * 60)
    print("☢️  FULL SYSTEM RESET")
    print("=" * 60 + "\n")
    
    print("This will DELETE:")
    print("  🗑️  Customer database (all customers and vehicles)")
    print("  🗑️  Appointment history")
    print("  🗑️  All Carfax data from Pinecone")
    print("\nThis will KEEP:")
    print("  ✅ Owner's manuals in Pinecone")
    print("  ✅ CSV service records")
    print("  ✅ Configuration (.env)")
    
    if not confirm_action("\n⚠️  Proceed with FULL RESET?"):
        print("\n❌ Reset cancelled.")
        return
    
    print("\n🚀 Starting reset...\n")
    
    # 1. Customer Database
    print("1️⃣ Resetting customer database...")
    reset_customer_database()
    
    # 2. Appointments
    print("\n2️⃣ Resetting appointments...")
    reset_appointments()
    
    # 3. Carfax Data
    print("\n3️⃣ Resetting Carfax data...")
    delete_carfax_data()
    
    print("\n" + "=" * 60)
    print("✅ RESET COMPLETE")
    print("=" * 60)
    print("\n💡 Next steps:")
    print("   1. Restart your bot: python main.py")
    print("   2. Bot will recreate empty customer database")
    print("   3. Add customers manually or let them register naturally")
    print()

if __name__ == "__main__":
    full_reset()
