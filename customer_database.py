import pandas as pd
import glob
import os
from typing import Optional, Dict, List
import re

class CustomerDatabase:
    """
    Manages customer service records from Rick Case Honda.
    Loads all historical CSV files and provides fast lookup.
    """
    
    def __init__(self, csv_folder="./data"):
        """
        Initialize the customer database.
        
        Args:
            csv_folder: Path to folder containing CSV files (default: ./data)
                       In production, put your CSV files in a 'data' folder next to your bot
        """
        self.df = None
        self.csv_folder = csv_folder
        self.load_data()
    
    def load_data(self):
        """Load all service record CSV files"""
        print("📚 Loading customer database...")
        
        # Create data folder if it doesn't exist
        if not os.path.exists(self.csv_folder):
            print(f"📁 Creating data folder: {self.csv_folder}")
            os.makedirs(self.csv_folder, exist_ok=True)
        
        # Find all service record files
        pattern = os.path.join(self.csv_folder, "RICKCASE_DAILY_SERVICE_RECORD_-_*.csv")
        files = glob.glob(pattern)
        
        if not files:
            print(f"⚠️  No customer database files found in {self.csv_folder}")
            print(f"💡 Expected filename pattern: RICKCASE_DAILY_SERVICE_RECORD_-_YYYY.csv")
            print(f"📂 Please place your CSV files in the '{self.csv_folder}' folder")
            self.df = pd.DataFrame()
            return
        
        # Load and combine all files
        dfs = []
        for file in sorted(files):
            try:
                df = pd.read_csv(file, encoding='latin-1')
                
                # Column names vary between years - normalize them
                column_mapping = {}
                for col in df.columns:
                    col_lower = col.lower().strip()
                    if 'tag' in col_lower:
                        column_mapping[col] = 'TAG'
                    elif 'ro' in col_lower or col.strip() == 'RO#':
                        column_mapping[col] = 'RO'
                    elif 'make' in col_lower or 'model' in col_lower:
                        column_mapping[col] = 'VEHICLE'
                    elif col_lower == 'name':
                        column_mapping[col] = 'NAME'
                    elif 'phone' in col_lower:
                        column_mapping[col] = 'PHONE'
                    elif 'description' in col_lower or 'service' in col_lower:
                        column_mapping[col] = 'SERVICE'
                    elif 'wait' in col_lower or 'drop' in col_lower:
                        column_mapping[col] = 'WAIT_DROP'
                
                df = df.rename(columns=column_mapping)
                
                # Keep only relevant columns (if they exist)
                keep_cols = ['TAG', 'RO', 'VEHICLE', 'NAME', 'PHONE', 'SERVICE', 'WAIT_DROP']
                available_cols = [col for col in keep_cols if col in df.columns]
                df = df[available_cols]
                
                dfs.append(df)
                print(f"   ✓ Loaded {os.path.basename(file)}: {len(df)} records")
            except Exception as e:
                print(f"   ✗ Error loading {file}: {e}")
        
        if not dfs:
            print("❌ No data could be loaded!")
            self.df = pd.DataFrame()
            return
        
        # Combine all years
        self.df = pd.concat(dfs, ignore_index=True)
        
        # Clean up - remove date rows and empty rows
        self.df = self.df.dropna(subset=['NAME', 'PHONE'])
        
        # Remove rows where NAME looks like a date (e.g., "09/01/2021")
        self.df = self.df[~self.df['NAME'].astype(str).str.contains(r'\d{2}/\d{2}/\d{2,4}', na=False)]
        
        self.df['PHONE'] = self.df['PHONE'].astype(str)
        self.df['NAME'] = self.df['NAME'].astype(str).str.strip().str.upper()
        
        print(f"\n✅ Loaded {len(self.df)} total service records")
        print(f"📊 Unique customers: {self.df['PHONE'].nunique()}")
    
    def normalize_phone(self, phone: str) -> str:
        """
        Normalize phone number to just digits for comparison.
        (954) 123-4567 → 9541234567
        """
        return re.sub(r'\D', '', str(phone))
    
    def search_by_phone(self, phone: str) -> Optional[Dict]:
        """
        Search for customer by phone number.
        Returns most recent service record if found.
        """
        if self.df is None or len(self.df) == 0:
            return None
        
        # Normalize the search phone
        search_phone = self.normalize_phone(phone)
        
        if not search_phone:
            return None
        
        # Search in database
        matches = self.df[self.df['PHONE'].apply(self.normalize_phone) == search_phone]
        
        if len(matches) == 0:
            return None
        
        # Get most recent record (last one)
        recent = matches.iloc[-1]
        
        # Get service history count
        visit_count = len(matches)
        
        # Get all vehicles they've brought in
        vehicles = matches['VEHICLE'].dropna().unique().tolist()
        
        return {
            'name': recent['NAME'],
            'phone': recent['PHONE'],
            'last_vehicle': recent.get('VEHICLE', 'Unknown'),
            'all_vehicles': vehicles,
            'last_service': recent.get('SERVICE', 'N/A'),
            'visit_count': visit_count,
            'is_returning': True
        }
    
    def search_by_name(self, name: str) -> List[Dict]:
        """
        Search for customers by name (partial match).
        Returns list of matches.
        """
        if self.df is None or len(self.df) == 0:
            return []
        
        # Normalize search name
        search_name = name.strip().upper()
        
        # Search for partial matches
        matches = self.df[self.df['NAME'].str.contains(search_name, na=False, case=False)]
        
        if len(matches) == 0:
            return []
        
        # Group by phone number (unique customers)
        results = []
        for phone in matches['PHONE'].unique():
            customer_records = matches[matches['PHONE'] == phone]
            recent = customer_records.iloc[-1]
            
            results.append({
                'name': recent['NAME'],
                'phone': recent['PHONE'],
                'last_vehicle': recent.get('VEHICLE', 'Unknown'),
                'visit_count': len(customer_records)
            })
        
        return results
    
    def get_customer_history(self, phone: str) -> List[Dict]:
        """
        Get full service history for a customer.
        """
        if self.df is None or len(self.df) == 0:
            return []
        
        search_phone = self.normalize_phone(phone)
        matches = self.df[self.df['PHONE'].apply(self.normalize_phone) == search_phone]
        
        history = []
        for _, record in matches.iterrows():
            history.append({
                'date': record.get('TAG', 'N/A'),
                'ro_number': record.get('RO', 'N/A'),
                'vehicle': record.get('VEHICLE', 'N/A'),
                'service': record.get('SERVICE', 'N/A'),
                'type': record.get('WAIT_DROP', 'N/A')
            })
        
        return history

# Global instance
customer_db = CustomerDatabase()

if __name__ == "__main__":
    # Test the database
    print("\n" + "="*50)
    print("TESTING CUSTOMER DATABASE")
    print("="*50 + "\n")
    
    if len(customer_db.df) > 0:
        # Get a sample phone number from the database
        sample_phone = customer_db.df['PHONE'].iloc[0]
        print(f"Testing with sample customer: {sample_phone}")
        result = customer_db.search_by_phone(sample_phone)
        
        if result:
            print(f"\n✅ FOUND RETURNING CUSTOMER:")
            print(f"   Name: {result['name']}")
            print(f"   Phone: {result['phone']}")
            print(f"   Last Vehicle: {result['last_vehicle']}")
            print(f"   Visit Count: {result['visit_count']}")
            print(f"   All Vehicles: {', '.join(result['all_vehicles'])}")
        else:
            print("❌ Customer not found")
    else:
        print("⚠️  No data loaded. Please add CSV files to the data folder.")
