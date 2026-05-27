import os

# Maximum allowed upload size in bytes (50 MB)
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", 50 * 1024 * 1024))

# Allowed archive extensions
ALLOWED_EXTENSIONS = {".zip", ".rar"}

# Expected number of DBF files inside the archive
EXPECTED_DBF_COUNT = 8

# Where extracted DBF files are stored for future operations
STORAGE_BASE = os.path.join(os.path.dirname(__file__), "..", "storage")