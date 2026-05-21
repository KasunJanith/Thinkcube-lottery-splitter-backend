import zipfile
import rarfile
import os

def is_valid_archive(file_path: str) -> bool:
    
    if zipfile.is_zipfile(file_path):
        return True
    if rarfile.is_rarfile(file_path):
        return True
    return False

def extract_archive(file_path: str, dest_dir: str) -> None:
    """
    Extract ZIP or RAR archive to destination directory.
    Raises ValueError if unsupported or extraction fails.
    """
    if zipfile.is_zipfile(file_path):
        with zipfile.ZipFile(file_path, 'r') as zf:
            # Security: ensure no path traversal
            for member in zf.namelist():
                member_path = os.path.join(dest_dir, member)
                # Check if final path is within dest_dir
                if not os.path.abspath(member_path).startswith(os.path.abspath(dest_dir)):
                    raise ValueError(f"Path traversal attempt detected: {member}")
            zf.extractall(dest_dir)
    elif rarfile.is_rarfile(file_path):
        with rarfile.RarFile(file_path) as rf:
            for member in rf.namelist():
                member_path = os.path.join(dest_dir, member)
                if not os.path.abspath(member_path).startswith(os.path.abspath(dest_dir)):
                    raise ValueError(f"Path traversal attempt detected: {member}")
            rf.extractall(dest_dir)
    else:
        raise ValueError("Unsupported archive format")