import os
from typing import List, Tuple, Dict, Any, Optional
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
    raise ValueError(f"No serial field found (looked for {SERIAL_CANDIDATE_FIELDS} with length {SERIAL_LENGTH}).")


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
    # If no records, create an empty table from source structure
    source = dbf.Table(source_path)
    source.open(dbf.READ_ONLY)
    new = source.new(output_path)
    new.open(dbf.READ_WRITE)
    if records:
        for rec in records:
            row = {name: rec.get(name) for name in field_names}
            new.append(row)
    new.close()
    source.close()


def split_dbf_by_agents(
    file_path: str,
    assignments: List[Tuple[str, int]],   # [(agent_name, count), ...]
    session_id: str,
    lottery_name: str,
    draw_number: str,
) -> dict:
    """
    Split the DBF file into parts for each agent, sequentially from first record,
    without overlapping. Returns parts, total_records, assigned_records, remaining.
    """
    dbf_obj = DBF(file_path, encoding='utf-8')
    serial_field = _get_serial_field(dbf_obj)

    # Read and sort all records by serial
    records = []
    for rec in dbf_obj:
        serial = rec.get(serial_field, '').strip()
        records.append((serial, rec))
    records.sort(key=lambda x: x[0])
    total_records = len(records)

    if not records:
        raise ValueError("DBF file has no records.")

    parts = []
    current_idx = 0
    for i, (agent, count) in enumerate(assignments, start=1):
        if count <= 0:
            continue
        end_idx = current_idx + count
        if end_idx > total_records:
            raise ValueError(f"Not enough records for agent '{agent}' at part {i}.")
        chunk = records[current_idx:end_idx]

        start_serial = chunk[0][0]
        end_serial = chunk[-1][0]

        output_filename = f"{lottery_name}{draw_number}_part_{i}_{agent}.dbf"
        output_dir = os.path.join(STORAGE_BASE, session_id)
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, output_filename)

        _write_dbf(file_path, output_path, [rec for _, rec in chunk], dbf_obj.field_names)

        parts.append({
            "part_number": i,
            "start_serial": start_serial,
            "end_serial": end_serial,
            "record_count": len(chunk),
            "saved_file": output_path,
            "agent": agent
        })
        current_idx = end_idx

    assigned_records = current_idx
    remaining_records = total_records - assigned_records

    return {
        "success": True,
        "original_file": os.path.basename(file_path),
        "parts": parts,
        "total_records": total_records,
        "assigned_records": assigned_records,
        "remaining_records": remaining_records,
    }