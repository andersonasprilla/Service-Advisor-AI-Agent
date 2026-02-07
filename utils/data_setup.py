"""
Data setup utility — copies CSV files into the data folder on startup.
"""

import os
import shutil
from config import DATA_FOLDER


def setup_data_folder(uploads_folder: str = "/mnt/user-data/uploads"):
    """Copy CSV files from uploads to data folder if needed."""
    os.makedirs(DATA_FOLDER, exist_ok=True)

    if not os.path.exists(uploads_folder):
        return

    csv_files = [
        f for f in os.listdir(uploads_folder)
        if f.startswith("RICKCASE_") and f.endswith(".csv")
    ]
    for csv_file in csv_files:
        src = os.path.join(uploads_folder, csv_file)
        dst = os.path.join(DATA_FOLDER, csv_file)
        if not os.path.exists(dst):
            shutil.copy2(src, dst)
            print(f"✅ Copied {csv_file} to data folder")
