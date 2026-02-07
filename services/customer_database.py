"""
Customer Database — Manages historical service records from Rick Case Honda.

Loads CSV files from the data folder and provides fast phone/name lookup.
"""

import pandas as pd
import glob
import os
import re
from typing import Optional, Dict, List
from config import DATA_FOLDER


class CustomerDatabase:
    """Loads all historical CSV files and provides fast customer lookup."""

    def __init__(self, csv_folder: str = DATA_FOLDER):
        self.df = pd.DataFrame()
        self.csv_folder = csv_folder
        self.load_data()

    # ─── Data Loading ─────────────────────────────────────────────

    def load_data(self):
        """Load and combine all service record CSV files."""
        print("📚 Loading customer database...")

        os.makedirs(self.csv_folder, exist_ok=True)

        pattern = os.path.join(self.csv_folder, "RICKCASE_DAILY_SERVICE_RECORD_-_*.csv")
        files = glob.glob(pattern)

        if not files:
            print(f"⚠️  No customer database files found in {self.csv_folder}")
            print(f"💡 Expected pattern: RICKCASE_DAILY_SERVICE_RECORD_-_YYYY.csv")
            return

        dfs = []
        for file in sorted(files):
            try:
                df = pd.read_csv(file, encoding="latin-1")
                df = self._normalize_columns(df)
                dfs.append(df)
                print(f"   ✓ Loaded {os.path.basename(file)}: {len(df)} records")
            except Exception as e:
                print(f"   ✗ Error loading {file}: {e}")

        if not dfs:
            print("❌ No data could be loaded!")
            return

        self.df = pd.concat(dfs, ignore_index=True)
        self._clean_data()

        print(f"\n✅ Loaded {len(self.df)} total service records")
        print(f"📊 Unique customers: {self.df['PHONE'].nunique()}")

    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize varying column names across CSV years."""
        column_mapping = {}
        for col in df.columns:
            col_lower = col.lower().strip()
            if "tag" in col_lower:
                column_mapping[col] = "TAG"
            elif "ro" in col_lower or col.strip() == "RO#":
                column_mapping[col] = "RO"
            elif "make" in col_lower or "model" in col_lower:
                column_mapping[col] = "VEHICLE"
            elif col_lower == "name":
                column_mapping[col] = "NAME"
            elif "phone" in col_lower:
                column_mapping[col] = "PHONE"
            elif "description" in col_lower or "service" in col_lower:
                column_mapping[col] = "SERVICE"
            elif "wait" in col_lower or "drop" in col_lower:
                column_mapping[col] = "WAIT_DROP"

        df = df.rename(columns=column_mapping)

        keep_cols = ["TAG", "RO", "VEHICLE", "NAME", "PHONE", "SERVICE", "WAIT_DROP"]
        available = [c for c in keep_cols if c in df.columns]
        return df[available]

    def _clean_data(self):
        """Remove junk rows, normalize strings."""
        self.df = self.df.dropna(subset=["NAME", "PHONE"])
        # Remove rows where NAME looks like a date
        self.df = self.df[
            ~self.df["NAME"].astype(str).str.contains(r"\d{2}/\d{2}/\d{2,4}", na=False)
        ]
        self.df["PHONE"] = self.df["PHONE"].astype(str)
        self.df["NAME"] = self.df["NAME"].astype(str).str.strip().str.upper()

    # ─── Phone Normalization ──────────────────────────────────────

    @staticmethod
    def normalize_phone(phone: str) -> str:
        """(954) 123-4567 → 9541234567"""
        return re.sub(r"\D", "", str(phone))

    # ─── Lookups ──────────────────────────────────────────────────

    def search_by_phone(self, phone: str) -> Optional[Dict]:
        """Search by phone number. Returns most recent record or None."""
        if self.df.empty:
            return None

        search_phone = self.normalize_phone(phone)
        if not search_phone:
            return None

        matches = self.df[self.df["PHONE"].apply(self.normalize_phone) == search_phone]
        if matches.empty:
            return None

        recent = matches.iloc[-1]
        return {
            "name": recent["NAME"],
            "phone": recent["PHONE"],
            "last_vehicle": recent.get("VEHICLE", "Unknown"),
            "all_vehicles": matches["VEHICLE"].dropna().unique().tolist(),
            "last_service": recent.get("SERVICE", "N/A"),
            "visit_count": len(matches),
            "is_returning": True,
        }

    def search_by_name(self, name: str) -> List[Dict]:
        """Search by name (partial match). Returns list of unique customers."""
        if self.df.empty:
            return []

        matches = self.df[
            self.df["NAME"].str.contains(name.strip().upper(), na=False, case=False)
        ]
        if matches.empty:
            return []

        results = []
        for phone in matches["PHONE"].unique():
            records = matches[matches["PHONE"] == phone]
            recent = records.iloc[-1]
            results.append({
                "name": recent["NAME"],
                "phone": recent["PHONE"],
                "last_vehicle": recent.get("VEHICLE", "Unknown"),
                "visit_count": len(records),
            })
        return results

    def get_customer_history(self, phone: str) -> List[Dict]:
        """Full service history for a customer."""
        if self.df.empty:
            return []

        search_phone = self.normalize_phone(phone)
        matches = self.df[self.df["PHONE"].apply(self.normalize_phone) == search_phone]

        return [
            {
                "date": row.get("TAG", "N/A"),
                "ro_number": row.get("RO", "N/A"),
                "vehicle": row.get("VEHICLE", "N/A"),
                "service": row.get("SERVICE", "N/A"),
                "type": row.get("WAIT_DROP", "N/A"),
            }
            for _, row in matches.iterrows()
        ]


# Global singleton
customer_db = CustomerDatabase()
