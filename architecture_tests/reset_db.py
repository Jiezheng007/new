import sys
from pathlib import Path

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.append(str(backend_dir))

from app.db.session import engine, Base
import app.models  # This imports all models so they register with Base.metadata


def reset_database():
    print("Starting database reset...")
    
    # Drop all existing tables
    print("Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    
    # Recreate all tables based on models
    print("Creating all tables...")
    Base.metadata.create_all(bind=engine)
    
    print("Database reset complete. All tables are now empty and freshly initialized.")


if __name__ == "__main__":
    reset_database()
