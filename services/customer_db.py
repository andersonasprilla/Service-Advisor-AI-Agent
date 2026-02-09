"""
Customer Database — SQLite-based with VIN support.

Each customer is identified by phone number and can have multiple vehicles.
Each vehicle has a VIN, decoded info (year/model/trim), and Pinecone namespaces
for both the owner's manual and Carfax data.

Tables:
  customers: id, phone, name, created_at
  vehicles:  id, customer_id, vin, year, make, model, trim, manual_namespace, carfax_namespace, is_primary
"""

import sqlite3
import os
import requests
from datetime import datetime
from config import DATA_FOLDER, VEHICLE_NAMESPACES

DB_PATH = os.path.join(DATA_FOLDER, "customers.db")


def _get_conn() -> sqlite3.Connection:
    """Get a connection with row_factory for dict-like access."""
    os.makedirs(DATA_FOLDER, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE NOT NULL,
            name TEXT,
            telegram_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            vin TEXT UNIQUE NOT NULL,
            year TEXT,
            make TEXT DEFAULT 'Honda',
            model TEXT,
            trim TEXT,
            manual_namespace TEXT,
            carfax_namespace TEXT,
            is_primary INTEGER DEFAULT 0,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES customers(id)
        );

        CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);
        CREATE INDEX IF NOT EXISTS idx_vehicles_vin ON vehicles(vin);
    """)
    conn.commit()
    conn.close()
    print("✅ Customer database initialized")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# VIN DECODER — Uses NHTSA's free API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def decode_vin(vin: str) -> dict | None:
    """
    Decode a VIN using the free NHTSA Vehicle API.
    
    Returns:
        dict with keys: year, make, model, trim, manual_namespace
        None if decode fails
    """
    vin = vin.strip().upper()
    if len(vin) != 17:
        print(f"   ⚠️ Invalid VIN length: {len(vin)}")
        return None

    try:
        url = f"https://vpic.nhtsa.dot.gov/api/vehicles/decodevin/{vin}?format=json"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        results = {item["Variable"]: item["Value"] for item in data.get("Results", [])}

        year = results.get("Model Year", "").strip()
        make = results.get("Make", "").strip()
        model = results.get("Model", "").strip()
        trim = results.get("Trim", "").strip()

        if not model:
            print(f"   ⚠️ NHTSA couldn't decode VIN: {vin}")
            return None

        # Map to owner's manual namespace
        manual_namespace = _map_to_manual_namespace(model, year)

        decoded = {
            "year": year,
            "make": make or "Honda",
            "model": model,
            "trim": trim,
            "manual_namespace": manual_namespace,
        }

        print(f"   🔍 VIN decoded: {year} {make} {model} {trim}")
        return decoded

    except Exception as e:
        print(f"   ❌ VIN decode failed: {e}")
        return None


def _map_to_manual_namespace(model: str, year: str) -> str | None:
    """
    Map a decoded model name to the Pinecone namespace for the owner's manual.
    
    Falls back to fuzzy matching (e.g., "Civic" -> "civic-2025").
    """
    model_lower = model.lower().strip()

    # Direct match: check if model is in VEHICLE_NAMESPACES
    if model_lower in VEHICLE_NAMESPACES:
        return VEHICLE_NAMESPACES[model_lower]

    # Try with year: e.g., "civic-2025"
    namespace_guess = f"{model_lower}-{year}"
    if namespace_guess in VEHICLE_NAMESPACES.values():
        return namespace_guess

    # Fuzzy: check if any key is contained in the model
    for key, namespace in VEHICLE_NAMESPACES.items():
        if key in model_lower or model_lower in key:
            return namespace

    print(f"   ⚠️ No manual namespace found for: {model} {year}")
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CUSTOMER CRUD
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def get_or_create_customer(phone: str, name: str = None, telegram_id: int = None) -> dict:
    """
    Find a customer by phone, or create a new one.
    
    Returns dict: {id, phone, name, telegram_id, vehicles: [...]}
    """
    conn = _get_conn()
    row = conn.execute("SELECT * FROM customers WHERE phone = ?", (phone,)).fetchone()

    if row:
        customer_id = row["id"]
        # Update telegram_id if provided and not set
        if telegram_id and not row["telegram_id"]:
            conn.execute("UPDATE customers SET telegram_id = ? WHERE id = ?", (telegram_id, customer_id))
            conn.commit()
        if name and not row["name"]:
            conn.execute("UPDATE customers SET name = ? WHERE id = ?", (name, customer_id))
            conn.commit()
    else:
        cursor = conn.execute(
            "INSERT INTO customers (phone, name, telegram_id) VALUES (?, ?, ?)",
            (phone, name, telegram_id),
        )
        customer_id = cursor.lastrowid
        conn.commit()

    # Fetch vehicles
    vehicles = conn.execute(
        "SELECT * FROM vehicles WHERE customer_id = ? ORDER BY is_primary DESC, added_at DESC",
        (customer_id,),
    ).fetchall()

    conn.close()

    return {
        "id": customer_id,
        "phone": phone,
        "name": name or (row["name"] if row else None),
        "telegram_id": telegram_id or (row["telegram_id"] if row else None),
        "vehicles": [dict(v) for v in vehicles],
    }


def add_vehicle(phone: str, vin: str, is_primary: bool = False, decoded: dict = None) -> dict | None:
    """
    Add a vehicle to a customer's profile.
    
    If decoded info is not provided, will attempt NHTSA decode.
    Returns the vehicle record or None if failed.
    """
    vin = vin.strip().upper()

    # Decode if not provided
    if not decoded:
        decoded = decode_vin(vin)
    if not decoded:
        decoded = {"year": "", "make": "Honda", "model": "", "trim": "", "manual_namespace": None}

    conn = _get_conn()

    # Make sure customer exists
    customer = conn.execute("SELECT id FROM customers WHERE phone = ?", (phone,)).fetchone()
    if not customer:
        conn.close()
        print(f"   ❌ No customer found for phone: {phone}")
        return None

    customer_id = customer["id"]

    # Check if VIN already exists
    existing = conn.execute("SELECT * FROM vehicles WHERE vin = ?", (vin,)).fetchone()
    if existing:
        conn.close()
        return dict(existing)

    # If setting as primary, un-primary the others
    if is_primary:
        conn.execute("UPDATE vehicles SET is_primary = 0 WHERE customer_id = ?", (customer_id,))

    # If this is the only vehicle, make it primary
    count = conn.execute("SELECT COUNT(*) as c FROM vehicles WHERE customer_id = ?", (customer_id,)).fetchone()["c"]
    if count == 0:
        is_primary = True

    carfax_namespace = f"carfax-{vin}"

    cursor = conn.execute(
        """INSERT INTO vehicles (customer_id, vin, year, make, model, trim, 
           manual_namespace, carfax_namespace, is_primary)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (customer_id, vin, decoded["year"], decoded["make"], decoded["model"],
         decoded["trim"], decoded["manual_namespace"], carfax_namespace, int(is_primary)),
    )

    vehicle_id = cursor.lastrowid
    conn.commit()

    vehicle = conn.execute("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone()
    conn.close()

    print(f"   ✅ Added vehicle: {decoded.get('year', '')} {decoded.get('model', '')} (VIN: {vin[:8]}...)")
    return dict(vehicle)


def get_customer_vehicles(phone: str) -> list[dict]:
    """Get all vehicles for a customer."""
    conn = _get_conn()
    customer = conn.execute("SELECT id FROM customers WHERE phone = ?", (phone,)).fetchone()
    if not customer:
        conn.close()
        return []

    vehicles = conn.execute(
        "SELECT * FROM vehicles WHERE customer_id = ? ORDER BY is_primary DESC",
        (customer["id"],),
    ).fetchall()
    conn.close()
    return [dict(v) for v in vehicles]


def get_primary_vehicle(phone: str) -> dict | None:
    """Get the primary (default) vehicle for a customer."""
    conn = _get_conn()
    customer = conn.execute("SELECT id FROM customers WHERE phone = ?", (phone,)).fetchone()
    if not customer:
        conn.close()
        return None

    vehicle = conn.execute(
        "SELECT * FROM vehicles WHERE customer_id = ? AND is_primary = 1",
        (customer["id"],),
    ).fetchone()
    conn.close()
    return dict(vehicle) if vehicle else None


def set_primary_vehicle(phone: str, vin: str) -> bool:
    """Set a specific vehicle as the primary for a customer."""
    conn = _get_conn()
    customer = conn.execute("SELECT id FROM customers WHERE phone = ?", (phone,)).fetchone()
    if not customer:
        conn.close()
        return False

    conn.execute("UPDATE vehicles SET is_primary = 0 WHERE customer_id = ?", (customer["id"],))
    conn.execute("UPDATE vehicles SET is_primary = 1 WHERE customer_id = ? AND vin = ?", (customer["id"], vin.upper()))
    conn.commit()
    conn.close()
    return True


def lookup_by_telegram_id(telegram_id: int) -> dict | None:
    """Find a customer by their Telegram user ID."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM customers WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if not row:
        conn.close()
        return None

    vehicles = conn.execute(
        "SELECT * FROM vehicles WHERE customer_id = ? ORDER BY is_primary DESC",
        (row["id"],),
    ).fetchall()
    conn.close()

    return {
        "id": row["id"],
        "phone": row["phone"],
        "name": row["name"],
        "telegram_id": row["telegram_id"],
        "vehicles": [dict(v) for v in vehicles],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CARFAX INGESTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def ingest_carfax(pdf_path: str, vin: str) -> bool:
    """
    Ingest a Carfax PDF into Pinecone under the carfax-{VIN} namespace.
    
    Usage:
        ingest_carfax("carfax_1HGCV1F34RA012345.pdf", "1HGCV1F34RA012345")
    """
    from langchain_community.document_loaders import PyPDFLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from services.clients import get_embeddings, get_pinecone_index

    vin = vin.strip().upper()
    namespace = f"carfax-{vin}"

    if not os.path.exists(pdf_path):
        print(f"❌ Carfax PDF not found: {pdf_path}")
        return False

    print(f"\n🚗 Ingesting Carfax for VIN: {vin}")
    print(f"   Namespace: {namespace}")
    print("-" * 50)

    # Load PDF
    loader = PyPDFLoader(pdf_path)
    raw_docs = loader.load()
    print(f"   ✅ Loaded {len(raw_docs)} pages")

    # Split into chunks
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=150)
    documents = splitter.split_documents(raw_docs)
    print(f"   ✅ Created {len(documents)} text chunks")

    # Embed and upload
    embeddings = get_embeddings()
    index = get_pinecone_index()
    batch_size = 100
    total = 0

    for i in range(0, len(documents), batch_size):
        batch = documents[i : i + batch_size]
        vectors = []

        for j, doc in enumerate(batch):
            vector_values = embeddings.embed_query(doc.page_content)
            vectors.append({
                "id": f"{namespace}-{i + j}",
                "values": vector_values,
                "metadata": {
                    "text": doc.page_content,
                    "page": doc.metadata.get("page", 0),
                    "source": f"carfax-{vin}",
                    "type": "carfax",
                },
            })

        index.upsert(vectors=vectors, namespace=namespace)
        total += len(batch)
        print(f"   ✅ Uploaded {total}/{len(documents)} chunks")

    print(f"\n🎉 Carfax ingested! {total} chunks → '{namespace}'")
    return True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# INIT ON IMPORT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

init_db()
