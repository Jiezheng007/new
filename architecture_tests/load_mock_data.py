import sys
import json
import hashlib
from datetime import datetime
from pathlib import Path

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.append(str(backend_dir))

from app.db.session import SessionLocal
from app.models.datasource import DataSource, OpinionItem

def load_data():
    db = SessionLocal()
    
    # 1. Create a dummy data source if not exists
    source_code = "mock_source_1"
    source = db.query(DataSource).filter_by(code=source_code).first()
    if not source:
        source = DataSource(
            code=source_code,
            name="Mock Data Source",
            source_type="json",
            url="mock_opinions_v3.json",
        )
        db.add(source)
        db.commit()
        db.refresh(source)
        
    source_id = source.id
    
    # 2. Read JSON file
    json_path = Path(__file__).resolve().parent.parent / "mock_opinions_v3.json"
    print(f"Reading data from {json_path}...")
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        records = data.get("records", [])
        
    print(f"Found {len(records)} records. Inserting into database...")
    
    # 3. Bulk insert
    batch_size = 5000
    items = []
    
    for i, r in enumerate(records):
        content_hash = hashlib.sha256(r.get("content", "").encode('utf-8')).hexdigest()
        published_at_str = r.get("published_at")
        published_at = None
        if published_at_str:
            try:
                published_at = datetime.fromisoformat(published_at_str)
            except ValueError:
                pass
                
        item = OpinionItem(
            source_id=source_id,
            source_code=source_code,
            source_type="json",
            external_id=r.get("external_id", ""),
            title=r.get("title", ""),
            content=r.get("content", ""),
            url=r.get("url", ""),
            author=r.get("author", ""),
            language=r.get("language", "zh"),
            published_at=published_at,
            content_hash=content_hash,
            origin="mock",
            raw_payload=json.dumps(r, ensure_ascii=False)
        )
        items.append(item)
        
        if len(items) >= batch_size:
            db.bulk_save_objects(items)
            db.commit()
            items.clear()
            print(f"Inserted {i+1} records...")
            
    if items:
        db.bulk_save_objects(items)
        db.commit()
        print(f"Inserted {len(records)} records in total.")
        
    db.close()
    print("Data loading complete.")

if __name__ == "__main__":
    load_data()
