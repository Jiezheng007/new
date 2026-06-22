import sys
import json
import hashlib
import random
from datetime import datetime
from pathlib import Path

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.append(str(backend_dir))

from app.db.session import SessionLocal, engine, Base
from app.models.datasource import DataSource, OpinionItem
from app.models.analysis import AnalysisResult
from app.models.alert import Alert
import app.models  # For metadata registration

def reset_and_load_data():
    db = SessionLocal()
    
    print("Dropping all tables...")
    Base.metadata.drop_all(bind=engine)
    print("Creating all tables...")
    Base.metadata.create_all(bind=engine)
    
    # 1. Create a dummy data source
    source_code = "mock_source_1"
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
    
    # 3. Insert loop
    batch_size = 5000
    opinions = []
    
    # For random generation
    sentiments = ["positive", "positive", "neutral", "negative", "negative"] # roughly 40/40/20
    
    for i, r in enumerate(records):
        content_hash = hashlib.sha256(r.get("content", "").encode('utf-8')).hexdigest()
        published_at_str = r.get("published_at")
        published_at = datetime.utcnow()
        if published_at_str:
            try:
                published_at = datetime.fromisoformat(published_at_str)
            except ValueError:
                pass
                
        # Generate OpinionItem
        item = OpinionItem(
            source_id=source_id,
            source_code=source_code,
            source_type="json",
            external_id=r.get("external_id", "") or f"ext_{i}",
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
        
        opinions.append(item)
        
        if len(opinions) >= batch_size:
            db.add_all(opinions)
            db.commit()
            
            analyses = []
            alerts = []
            for op in opinions:
                sentiment = random.choice(sentiments)
                if sentiment == "negative":
                    score = random.randint(50, 100)
                elif sentiment == "positive":
                    score = random.randint(0, 30)
                else:
                    score = random.randint(30, 50)
                    
                if score >= 80:
                    level = "severe"
                elif score >= 60:
                    level = "high"
                elif score >= 40:
                    level = "medium"
                else:
                    level = "low"
                    
                analysis = AnalysisResult(
                    opinion_item_id=op.id,
                    status="success",
                    sentiment=sentiment,
                    confidence=random.uniform(0.6, 1.0),
                    provider="mock_provider",
                    score=score,
                    level=level,
                    factors="[]",
                    explanation="Mock generated analysis",
                    analyzed_at=op.published_at or datetime.utcnow()
                )
                analyses.append(analysis)
                
                if level in ("high", "severe"):
                    alert = Alert(
                        opinion_item_id=op.id,
                        risk_level=level,
                        risk_score=score,
                        status="pending",
                        trigger_explanation="Mock generated alert explanation"
                    )
                    alerts.append(alert)
                    
            db.add_all(analyses)
            if alerts:
                db.add_all(alerts)
            db.commit()
            
            opinions.clear()
            print(f"Processed {i+1} records...")
            
    # Process remaining
    if opinions:
        db.add_all(opinions)
        db.commit()
        
        analyses = []
        alerts = []
        for op in opinions:
            sentiment = random.choice(sentiments)
            if sentiment == "negative":
                score = random.randint(50, 100)
            elif sentiment == "positive":
                score = random.randint(0, 30)
            else:
                score = random.randint(30, 50)
                
            if score >= 80:
                level = "severe"
            elif score >= 60:
                level = "high"
            elif score >= 40:
                level = "medium"
            else:
                level = "low"
                
            analysis = AnalysisResult(
                opinion_item_id=op.id,
                status="success",
                sentiment=sentiment,
                confidence=random.uniform(0.6, 1.0),
                provider="mock_provider",
                score=score,
                level=level,
                factors="[]",
                explanation="Mock generated analysis",
                analyzed_at=op.published_at or datetime.utcnow()
            )
            analyses.append(analysis)
            
            if level in ("high", "severe"):
                alert = Alert(
                    opinion_item_id=op.id,
                    risk_level=level,
                    risk_score=score,
                    status="pending",
                    trigger_explanation="Mock generated alert explanation"
                )
                alerts.append(alert)
                
        db.add_all(analyses)
        if alerts:
            db.add_all(alerts)
        db.commit()
        print(f"Processed {len(records)} records in total.")
        
    db.close()
    print("Data loading complete.")

if __name__ == "__main__":
    reset_and_load_data()
