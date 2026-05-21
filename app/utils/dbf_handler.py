import os
import re
from typing import List, Tuple, Optional
from dbfread import DBF
from app.config import EXPECTED_DBF_COUNT

FILENAME_PATTERN = re.compile(r'^([A-Za-z]+)(\d+)\.dbf$', re.IGNORECASE)

# List of possible serial field names (case‑insensitive matching)
SERIAL_CANDIDATE_FIELDS = ['code', 'prn_code']
SERIAL_LENGTH = 11


def find_serial_field(dbf: DBF) -> Optional[str]:
    """Return the field name (in DBF) that is a candidate for the 11‑char serial."""
    for candidate in SERIAL_CANDIDATE_FIELDS:
        for field in dbf.fields:
            if field.name.lower() == candidate and field.length == SERIAL_LENGTH:
                return field.name  # return the actual field name as in the file
    return None


def extract_serial_range(dbf: DBF, serial_field: str) -> Tuple[str, str]:
    """
    Return (first_serial, last_serial) by iterating through the DBF file.
    Assumes file is in ascending order, but we keep first and last anyway.
    """
    first_serial = None
    last_serial = None

    for record in dbf:
        value = record.get(serial_field, '').strip()
        if first_serial is None:
            first_serial = value
        last_serial = value   # overwritten on every record

    if first_serial is None:
        raise ValueError(f"No records found to extract serial from field '{serial_field}'")
    return first_serial, last_serial


def process_dbf_files(extract_dir: str, expected_count: int = EXPECTED_DBF_COUNT) -> List[dict]:
    """Process all DBF files and return lottery info including serial range."""
    dbf_files = []
    for root, dirs, files in os.walk(extract_dir):
        for file in files:
            if file.lower().endswith('.dbf'):
                dbf_files.append(os.path.join(root, file))

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

        try:
            # Open the DBF twice: once for record count (fast header read),
            # once for serial extraction (needs iteration).
            # But we can do everything in one pass to be efficient.
            dbf = DBF(full_path, encoding='utf-8')

            # 1. Record count from header (no iteration)
            record_count = len(dbf)

            # 2. Detect serial field and extract range
            serial_field = find_serial_field(dbf)
            if serial_field is None:
                raise ValueError(
                    f"No serial field found (expected one of {SERIAL_CANDIDATE_FIELDS} "
                    f"with length {SERIAL_LENGTH})."
                )

            start_serial, end_serial = extract_serial_range(dbf, serial_field)

        except Exception as e:
            raise ValueError(f"Failed to read DBF file '{filename}': {str(e)}")

        results.append({
            "lottery_name": lottery_name,
            "draw_number": draw_number,
            "file_name": filename,
            "record_count": record_count,
            "serial_field_used": serial_field,
            "start_serial": start_serial,
            "end_serial": end_serial,
        })

    return results