#!/usr/bin/env python3
"""
Debug script to test customer database phone lookup.

Usage:
  python debug_phone_lookup.py
"""

import re
from services.customer_database import CustomerDatabase


def normalize_phone(phone: str) -> str:
    return re.sub(r"\D", "", str(phone))


def test_phone_lookup():
    print("\n" + "=" * 60)
    print("CUSTOMER DATABASE PHONE LOOKUP DEBUG")
    print("=" * 60 + "\n")

    db = CustomerDatabase()

    if db.df.empty:
        print("❌ No customer data loaded!")
        print("Make sure CSV files are in the ./data folder")
        return

    print(f"✅ Loaded {len(db.df)} records")
    print(f"📊 Unique phone numbers: {db.df['PHONE'].nunique()}\n")

    # Show sample data
    print("📋 SAMPLE DATA (first 5 rows):")
    print("-" * 60)
    for _, row in db.df[["NAME", "PHONE", "VEHICLE"]].head(5).iterrows():
        print(f"Name: {row['NAME']:<25} Phone: {row['PHONE']:<20} Vehicle: {row.get('VEHICLE', 'N/A')}")
    print()

    # Show unique phone numbers
    print("📞 UNIQUE PHONE NUMBERS (first 20):")
    print("-" * 60)
    unique_phones = db.df["PHONE"].unique()[:20]
    for i, phone in enumerate(unique_phones, 1):
        print(f"{i:2}. {str(phone):<20} → normalized: {normalize_phone(phone)}")
    print()

    # Auto-test with first phone in DB
    print("🔍 TEST PHONE LOOKUP")
    print("-" * 60)

    if len(unique_phones) > 0:
        test_phone = str(unique_phones[0])
        print(f"\n1. Testing with database phone: {test_phone}")
        result = db.search_by_phone(test_phone)
        if result:
            print(f"   ✅ FOUND: {result['name']} | {result['last_vehicle']} | {result['visit_count']} visits")
        else:
            print("   ❌ NOT FOUND")

        # Test different formats
        digits = normalize_phone(test_phone)
        formats = [
            test_phone,
            digits,
            f"({digits[:3]}) {digits[3:6]}-{digits[6:]}" if len(digits) == 10 else test_phone,
        ]
        print("\n2. Testing format variations:")
        for fmt in formats:
            result = db.search_by_phone(fmt)
            status = "✅ FOUND" if result else "❌ NOT FOUND"
            print(f"   {fmt:<20} → {status}")

    # Manual test
    print("\n" + "=" * 60)
    test_input = input("\nEnter a phone number to test (or Enter to skip): ").strip()

    if test_input:
        print(f"\nSearching for: {test_input} (normalized: {normalize_phone(test_input)})")
        result = db.search_by_phone(test_input)

        if result:
            print("\n✅ CUSTOMER FOUND!")
            print(f"   Name:        {result['name']}")
            print(f"   Phone:       {result['phone']}")
            print(f"   Last Vehicle: {result['last_vehicle']}")
            print(f"   All Vehicles: {', '.join(result['all_vehicles'])}")
            print(f"   Last Service: {result['last_service']}")
            print(f"   Visit Count:  {result['visit_count']}")
        else:
            print("\n❌ NOT FOUND")
            search_norm = normalize_phone(test_input)
            partial = db.df[
                db.df["PHONE"]
                .apply(lambda x: normalize_phone(str(x)))
                .str.contains(search_norm[:7] if len(search_norm) >= 7 else search_norm)
            ]
            if not partial.empty:
                print(f"\n⚠️ Found {len(partial)} partial matches:")
                for _, row in partial.head(5).iterrows():
                    print(f"   {row['NAME']:<25} {row['PHONE']}")
            else:
                print("No partial matches either.")


if __name__ == "__main__":
    test_phone_lookup()
