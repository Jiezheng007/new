import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.models
from app.db.session import engine, Base
from app.services.bootstrap import init_db

def main():
    print("Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    print("Re-initializing database...")
    init_db()
    print("Database reset successfully.")

if __name__ == "__main__":
    main()
