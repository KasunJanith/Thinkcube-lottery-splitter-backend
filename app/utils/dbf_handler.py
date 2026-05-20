import os
import re
from typing import List
from dbfread import DBF
from app.config import EXPECTED_DBF_COUNT

# Pattern: lottery name (letters only) followed by digits, then .dbf
FILENAME_PATTERN = re.compile(r'^([A-Za-z]+)(\d+)\.dbf$', re.IGNORECASE)

def process_dbf_files(extract_dir: str, expected_count: int = EXPECTED_DBF_COUNT) -> List[dict]:
    """
    Walk through extracted directory, collect .dbf files, validate naming,
    read record counts, and return list of lottery info dictionaries.
    """
    dbf_files = []
    for root, dirs, files in os.walk(extract_dir):
        for file in files:
            if file.lower().endswith('.dbf'):
                dbf_files.append(os.path.join(root, file))

    # Check exact count
    if len(dbf_files) != expected_count:
        raise ValueError(
            f"Expected {expected_count} DBF files, but found {len(dbf_files)} in the archive."
        )

    results = []
    for full_path in dbf_files:
        filename = os.path.basename(full_path)
        match = FILENAME_PATTERN.match(filename)
        if not match:
            raise ValueError(
                f"Invalid DBF filename '{filename}'. "
                f"Must be in format: <lottery_name><draw_number>.dbf (e.g., Maha6192.dbf)."
            )

        lottery_name = match.group(1)
        draw_number = match.group(2)

        # Open DBF and count records
        try:
            dbf = DBF(full_path, encoding='utf-8')  # change to 'latin-1' if needed
            record_count = len(dbf)                 # <-- THIS IS THE FIX
        except Exception as e:
            raise ValueError(f"Failed to read DBF file '{filename}': {str(e)}")

        results.append({
            "lottery_name": lottery_name,
            "draw_number": draw_number,
            "file_name": filename,
            "record_count": record_count
        })

    return results