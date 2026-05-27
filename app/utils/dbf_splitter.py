import os
from typing import List, Optional, Dict, Any
import dbf
from dbfread import DBF
from app.config import STORAGE_BASE

SERIAL_CANDIDATE_FIELDS = ['code', 'prn_code']
SERIAL_LENGTH = 11


def _get_serial_field(dbf_obj: DBF) -> str:
    """Find the field name that holds the 11‑char serial number."""
    for candidate in SERIAL_CANDIDATE_FIELDS:
        for field in dbf_obj.fields:
            if field.name.lower() == candidate and field.length == SERIAL_LENGTH:
                return field.name
    raise ValueError(
        f"No serial field found (looked for {SERIAL_CANDIDATE_FIELDS} with length {SERIAL_LENGTH})."
    )


def split_dbf(
    file_path: str,
    agent_count: int,
    portion_size: Optional[int],
    session_id: str,
    lottery_name: str,
    draw_number: str,
) -> List[Dict[str, Any]]:
    """
    Split a DBF file into parts based on serial order.

    - If portion_size is given and > 0, each part gets exactly that many records
      (except the last, which may be smaller).
    - If portion_size is None or 0, records are divided equally among agent_count.
    - Saves each part as a new DBF file and returns a list of part info dicts.
    """
    # 1. Read DBF and determine serial field
    dbf_obj = DBF(file_path, encoding='utf-8')
    serial_field = _get_serial_field(dbf_obj)

    # 2. Read all records into a list and sort by serial
    records = []
    for rec in dbf_obj:
        serial = rec.get(serial_field, '').strip()
        records.append((serial, rec))
    if not records:
        raise ValueError("The DBF file contains no records.")

    # Sort by serial number (string comparison, assuming lexicographic order is correct)
    records.sort(key=lambda x: x[0])

    total_records = len(records)

    # 3. Determine chunk sizes
    if portion_size and portion_size > 0:
        # Fixed portion size
        chunk_sizes = []
        remaining = total_records
        while remaining > 0:
            size = min(portion_size, remaining)
            chunk_sizes.append(size)
            remaining -= size
    else:
        # Auto portion: split equally among agent_count
        base_size = total_records // agent_count
        remainder = total_records % agent_count
        chunk_sizes = [base_size + (1 if i < remainder else 0) for i in range(agent_count)]

    # 4. Split records into chunks and prepare output
    parts = []
    start_idx = 0
    for i, size in enumerate(chunk_sizes):
        if size == 0:
            continue   # safety: skip empty parts
        end_idx = start_idx + size
        chunk = records[start_idx:end_idx]
        start_serial = chunk[0][0]
        end_serial = chunk[-1][0]

        # 5. Save chunk as new DBF file
        output_filename = f"{lottery_name}{draw_number}_part_{i+1}.dbf"
        output_dir = os.path.join(STORAGE_BASE, session_id)
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_filename)

        _write_dbf(
            source_path=file_path,
            output_path=output_path,
            records=[rec for _, rec in chunk],
            field_names=dbf_obj.field_names,
        )

        parts.append({
            "part_number": i + 1,
            "start_serial": start_serial,
            "end_serial": end_serial,
            "record_count": len(chunk),
            "saved_file": output_path,
        })
        start_idx = end_idx

    return parts


def _write_dbf(
    source_path: str,
    output_path: str,
    records: List[Dict[str, Any]],
    field_names: List[str],
):
    """
    Create a new DBF file with the same structure as the source file,
    and fill it with the given records (list of dictionaries).
    """
    if not records:
        # If no records, still create an empty table with the same structure
        source = dbf.Table(source_path)
        source.open(dbf.READ_ONLY)
        new = source.new(output_path)
        new.open(dbf.READ_WRITE)
        new.close()
        source.close()
        return

    # Open the source file to clone its structure
    source = dbf.Table(source_path)
    source.open(dbf.READ_ONLY)

    # Create a new table using the source's structure
    new = source.new(output_path)
    new.open(dbf.READ_WRITE)

    # Append each record as a dictionary (field names are keys)
    for rec in records:
        # Ensure all expected fields are present (fill missing with None)
        row = {name: rec.get(name) for name in field_names}
        new.append(row)

    new.close()
    source.close()