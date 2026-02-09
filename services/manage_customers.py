"""
Customer & Vehicle Management CLI

Usage:
  python manage_customers.py add-customer --phone "(954) 243-1238" --name "John Doe"
  python manage_customers.py add-vin --phone "(954) 243-1238" --vin "1HGCV1F34RA012345"
  python manage_customers.py ingest-carfax --vin "1HGCV1F34RA012345" --pdf "carfax_john.pdf"
  python manage_customers.py add-and-ingest --phone "(954) 243-1238" --name "John Doe" --vin "1HGCV1F34RA012345" --pdf "carfax_john.pdf"
  python manage_customers.py list --phone "(954) 243-1238"
  python manage_customers.py list-all
"""

import argparse
import sys
from services.customer_db import (
    get_or_create_customer,
    add_vehicle,
    get_customer_vehicles,
    get_primary_vehicle,
    decode_vin,
    ingest_carfax,
    _get_conn,
)


def cmd_add_customer(args):
    """Add a new customer."""
    customer = get_or_create_customer(args.phone, name=args.name)
    print(f"\n✅ Customer ready:")
    print(f"   ID: {customer['id']}")
    print(f"   Name: {customer['name']}")
    print(f"   Phone: {customer['phone']}")
    print(f"   Vehicles: {len(customer['vehicles'])}")


def cmd_add_vin(args):
    """Add a VIN to a customer."""
    # Make sure customer exists
    customer = get_or_create_customer(args.phone)

    # Decode and add
    decoded = decode_vin(args.vin)
    vehicle = add_vehicle(args.phone, args.vin, is_primary=args.primary, decoded=decoded)

    if vehicle:
        print(f"\n✅ Vehicle added:")
        print(f"   VIN: {vehicle['vin']}")
        print(f"   Vehicle: {vehicle['year']} {vehicle['make']} {vehicle['model']} {vehicle['trim']}")
        print(f"   Manual NS: {vehicle['manual_namespace']}")
        print(f"   Carfax NS: {vehicle['carfax_namespace']}")
        print(f"   Primary: {'Yes' if vehicle['is_primary'] else 'No'}")
    else:
        print("❌ Failed to add vehicle")


def cmd_ingest_carfax(args):
    """Ingest a Carfax PDF for a VIN."""
    success = ingest_carfax(args.pdf, args.vin)
    if success:
        print(f"\n✅ Carfax ingested for VIN: {args.vin}")
    else:
        print(f"\n❌ Carfax ingestion failed")


def cmd_add_and_ingest(args):
    """One-shot: add customer, add VIN, ingest Carfax."""
    print("=" * 60)
    print("FULL CUSTOMER SETUP")
    print("=" * 60)

    # 1. Customer
    customer = get_or_create_customer(args.phone, name=args.name)
    print(f"\n1️⃣ Customer: {customer['name']} ({customer['phone']})")

    # 2. Decode + Add VIN
    decoded = decode_vin(args.vin)
    vehicle = add_vehicle(args.phone, args.vin, is_primary=True, decoded=decoded)
    if vehicle:
        print(f"2️⃣ Vehicle: {vehicle['year']} {vehicle['make']} {vehicle['model']}")
    else:
        print("❌ Vehicle add failed")
        return

    # 3. Ingest Carfax
    if args.pdf:
        print(f"3️⃣ Ingesting Carfax...")
        ingest_carfax(args.pdf, args.vin)
    else:
        print("3️⃣ No Carfax PDF provided — skipping ingestion")

    print(f"\n{'=' * 60}")
    print("✅ SETUP COMPLETE")
    print(f"{'=' * 60}")


def cmd_list(args):
    """List vehicles for a customer."""
    vehicles = get_customer_vehicles(args.phone)
    if not vehicles:
        print(f"No vehicles found for {args.phone}")
        return

    print(f"\n🚗 Vehicles for {args.phone}:")
    print("-" * 50)
    for v in vehicles:
        primary = " ⭐ PRIMARY" if v["is_primary"] else ""
        print(f"   {v['year']} {v['make']} {v['model']} {v['trim']}{primary}")
        print(f"      VIN: {v['vin']}")
        print(f"      Manual: {v['manual_namespace']}")
        print(f"      Carfax: {v['carfax_namespace']}")
        print()


def cmd_list_all(args):
    """List all customers and their vehicles."""
    conn = _get_conn()
    customers = conn.execute("SELECT * FROM customers ORDER BY created_at DESC").fetchall()

    if not customers:
        print("No customers in database.")
        conn.close()
        return

    print(f"\n📋 All Customers ({len(customers)}):")
    print("=" * 60)

    for c in customers:
        vehicles = conn.execute(
            "SELECT * FROM vehicles WHERE customer_id = ? ORDER BY is_primary DESC",
            (c["id"],),
        ).fetchall()

        print(f"\n👤 {c['name'] or 'Unknown'} — {c['phone']}")
        if vehicles:
            for v in vehicles:
                primary = " ⭐" if v["is_primary"] else ""
                print(f"   🚗 {v['year']} {v['make']} {v['model']}{primary} — VIN: {v['vin'][:11]}...")
        else:
            print("   (no vehicles)")

    conn.close()
    print(f"\n{'=' * 60}")


def main():
    parser = argparse.ArgumentParser(description="Rick Case Honda — Customer Manager")
    sub = parser.add_subparsers(dest="command")

    # add-customer
    p1 = sub.add_parser("add-customer", help="Add a new customer")
    p1.add_argument("--phone", required=True)
    p1.add_argument("--name", default=None)

    # add-vin
    p2 = sub.add_parser("add-vin", help="Add a VIN to a customer")
    p2.add_argument("--phone", required=True)
    p2.add_argument("--vin", required=True)
    p2.add_argument("--primary", action="store_true")

    # ingest-carfax
    p3 = sub.add_parser("ingest-carfax", help="Ingest a Carfax PDF")
    p3.add_argument("--vin", required=True)
    p3.add_argument("--pdf", required=True)

    # add-and-ingest (all-in-one)
    p4 = sub.add_parser("add-and-ingest", help="Add customer + VIN + ingest Carfax")
    p4.add_argument("--phone", required=True)
    p4.add_argument("--name", default=None)
    p4.add_argument("--vin", required=True)
    p4.add_argument("--pdf", default=None)

    # list
    p5 = sub.add_parser("list", help="List vehicles for a customer")
    p5.add_argument("--phone", required=True)

    # list-all
    sub.add_parser("list-all", help="List all customers")

    args = parser.parse_args()

    commands = {
        "add-customer": cmd_add_customer,
        "add-vin": cmd_add_vin,
        "ingest-carfax": cmd_ingest_carfax,
        "add-and-ingest": cmd_add_and_ingest,
        "list": cmd_list,
        "list-all": cmd_list_all,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
