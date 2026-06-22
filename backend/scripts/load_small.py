import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal
from app.services.importers import parse_json
from app.models.datasource import DataSource
from app.services.ingestion import ingest_records
from app.services.analysis import opinions_by_ids, analyze_batch

def main():
    db = SessionLocal()
    # Read from the root directory where the script generates the file
    text = Path("../mock_opinions_small.json").read_text(encoding="utf-8")
    records, errors = parse_json(text)
    source = db.query(DataSource).filter(DataSource.code == "import_json").one()
    res = ingest_records(db, source, records, origin="import_json")
    print(f"Loaded {res.accepted} records. Duplicate: {res.duplicate}. Errors: {len(errors)}")
    
    if res.sample_ids:
        opinions = opinions_by_ids(db, res.sample_ids)
        analyzed = analyze_batch(db, opinions)
        print(f"Analyzed {len(analyzed)} records using risk rules.")
    
    db.commit()

if __name__ == "__main__":
    main()
