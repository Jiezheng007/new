"""Bootstrap script: initialise the database with roles and a default admin."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.bootstrap import init_db  # noqa: E402


def main() -> None:
    init_db()
    print("Database initialised. Default admin: admin / admin123")


if __name__ == "__main__":
    main()
