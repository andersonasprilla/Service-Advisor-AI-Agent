#!/usr/bin/env python3
"""
Debug script to test customer database phone lookup
"""

import pandas as pd
import re
from customer_database import CustomerDatabase

def normalize_phone(phone: str) -> str:
    """Normalize phone number to just digits"""
    return re.sub(r'\D', '', str(phone))

def test_phone_lookup():
    print("\n" + "="*60)
    print("CUSTOMER DATABASE PHONE LOOKUP DEBUG")
    print("="*60 + "\n")
    
    # Load database
    db = CustomerDatabase(csv_folder="./data")
    
    if len(db.df) == 0:
        print("❌ No customer data loaded!")
        print("Make sure CSV files are in the ./data folder")
        return
    
    print(f"✅ Loaded {len(db.df)} records")
    print(f"📊 Unique phone numbers: {db.df['PHONE'].nunique()}\n")
    
    # Show sample data
    print("📋 SAMPLE DATA (first 5 rows):")
    print("-" * 60)
    if 'PHONE' in db.df.columns:
        sample = db.df[['NAME', 'PHONE', 'VEHICLE']].head(5)
        for idx, row in sample.iterrows():
            print(f"Name: {row['NAME']:<25} Phone: {row['PHONE']:<20} Vehicle: {row.get('VEHICLE', 'N/A')}")
    print()
    
    # Show all unique phone numbers (first 20)
    print("📞 UNIQUE PHONE NUMBERS IN DATABASE (first 20):")
    print("-" * 60)
    unique_phones = db.df['PHONE'].unique()[:20]
    for i, phone in enumerate(unique_phones, 1):
        normalized = normalize_phone(str(phone))
        print(f"{i:2}. {str(phone):<20} → normalized: {normalized}")
    print()
    
    # Interactive test
    print("🔍 TEST PHONE LOOKUP")
    print("-" * 60)
    
    # Try a phone from database
    if len(unique_phones) > 0:
        test_phone = str(unique_phones[0])
        print(f"\n1. Testing with actual phone from database: {test_phone}")
        result = db.search_by_phone(test_phone)
        if result:
            print("   ✅ FOUND!")
            print(f"   Name: {result['name']}")
            print(f"   Phone: {result['phone']}")
            print(f"   Last Vehicle: {result['last_vehicle']}")
            print(f"   Visit Count: {result['visit_count']}")
        else:
            print("   ❌ NOT FOUND")
    
    # Test with different formats
    print("\n2. Testing different phone formats:")
    test_formats = [
        test_phone,
        normalize_phone(test_phone),  # Just digits
        f"({test_phone[:3]}) {test_phone[3:6]}-{test_phone[6:]}" if len(normalize_phone(test_phone)) == 10 else test_phone,
    ]
    
    for fmt in test_formats:
        result = db.search_by_phone(fmt)
        status = "✅ FOUND" if result else "❌ NOT FOUND"
        print(f"   {fmt:<20} → {status}")
    
    # Manual test
    print("\n" + "="*60)
    print("MANUAL TEST")
    print("="*60)
    test_input = input("\nEnter a phone number to test (or press Enter to skip): ").strip()
    
    if test_input:
        print(f"\nSearching for: {test_input}")
        print(f"Normalized: {normalize_phone(test_input)}")
        
        result = db.search_by_phone(test_input)
        
        if result:
            print("\n✅ CUSTOMER FOUND!")
            print(f"Name: {result['name']}")
            print(f"Phone: {result['phone']}")
            print(f"Last Vehicle: {result['last_vehicle']}")
            print(f"All Vehicles: {', '.join(result['all_vehicles'])}")
            print(f"Last Service: {result['last_service']}")
            print(f"Visit Count: {result['visit_count']}")
        else:
            print("\n❌ CUSTOMER NOT FOUND")
            
            # Check if phone exists in any format
            print("\nSearching database directly...")
            search_normalized = normalize_phone(test_input)
            
            # Try to find partial matches
            matches = db.df[db.df['PHONE'].apply(lambda x: normalize_phone(str(x))).str.contains(search_normalized[:7] if len(search_normalized) >= 7 else search_normalized)]
            
            if len(matches) > 0:
                print(f"\n⚠️  Found {len(matches)} partial matches:")
                for idx, row in matches.head(5).iterrows():
                    print(f"   {row['NAME']:<25} {row['PHONE']}")
            else:
                print("\n❌ No matches found at all")

if __name__ == "__main__":
    test_phone_lookup()
