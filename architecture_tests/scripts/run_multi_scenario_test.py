import subprocess
import time
import os
import sys
import psutil
from pathlib import Path
import csv

try:
    import colorama
    colorama.init()
except ImportError:
    pass

class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent.parent
BACKEND_DIR = ROOT_DIR / "backend"
GENERATE_SCRIPT = BACKEND_DIR / "scripts" / "generate_mock_data.py"
LOCUST_FILE = SCRIPT_DIR / "locust_extreme.py"

SCENARIOS = [10000, 100000, 200000]
USERS = 100
SPAWN_RATE = 20
RUN_TIME = "45s"

def run_command(cmd, cwd=None, wait=True):
    print(f"  {Colors.OKBLUE}>{Colors.ENDC} 运行命令: {' '.join(cmd)}")
    if wait:
        result = subprocess.run(cmd, cwd=cwd)
        if result.returncode != 0:
            print(f"  {Colors.FAIL}! 命令执行失败，退出代码: {result.returncode}{Colors.ENDC}")
            raise Exception("Command failed")
    else:
        return subprocess.Popen(cmd, cwd=cwd)

def write_db_loader_script(data_file_name):
    loader_path = SCRIPT_DIR / "temp_load_multi.py"
    loader_code = f"""
import sys
from pathlib import Path
backend_dir = Path(r'{BACKEND_DIR}')
sys.path.append(str(backend_dir))

from app.db.session import SessionLocal, engine, Base
from app.models.datasource import DataSource, OpinionItem
from app.models.analysis import AnalysisResult
from app.models.alert import Alert
import json, random, hashlib
from datetime import datetime, timezone

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

db = SessionLocal()
source = DataSource(code="multi_test", name="Multi Test", source_type="json", url="{data_file_name}.json")
db.add(source)
db.commit()
db.refresh(source)

data_path = Path(r'{ROOT_DIR / (data_file_name + ".json")}')
with open(data_path, "r", encoding="utf-8") as f:
    records = json.load(f)["records"]

batch_size = 5000
opinions, analyses, alerts = [], [], []
sentiments = ["positive", "neutral", "negative", "negative"] 

for i, r in enumerate(records):
    published_at = datetime.now(timezone.utc)
    item = OpinionItem(
        source_id=source.id, source_code="multi_test", source_type="json",
        external_id=f"mt_{{i}}", title=r["title"], content=r["content"],
        url=r["url"], author=r["author"], language="zh", published_at=published_at,
        content_hash=hashlib.md5((r["content"] + str(i)).encode()).hexdigest(), origin="mock"
    )
    opinions.append(item)
    
    if len(opinions) >= batch_size:
        db.add_all(opinions)
        db.commit()
        for op in opinions:
            sentiment = random.choice(sentiments)
            score = random.randint(50, 100) if sentiment == "negative" else random.randint(0, 40)
            level = "high" if score > 60 else "low"
            
            analyses.append(AnalysisResult(opinion_item_id=op.id, status="success", sentiment=sentiment, provider="test", score=score, level=level))
            if level == "high":
                alerts.append(Alert(opinion_item_id=op.id, risk_level=level, risk_score=score, status="pending"))
        
        db.add_all(analyses)
        db.add_all(alerts)
        db.commit()
        opinions, analyses, alerts = [], [], []

if opinions:
    db.add_all(opinions)
    db.commit()
db.close()
"""
    with open(loader_path, "w", encoding="utf-8") as f:
        f.write(loader_code)
    return loader_path

def parse_metrics(stats_file):
    metrics = {}
    if not os.path.exists(stats_file):
        return metrics
    
    with open(stats_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("Name", "")
            if "dashboard/summary" in name:
                key = "工作台轮询 (GET /api/dashboard/summary)"
            elif "opinions" in name:
                key = "舆情交叉检索 (GET /api/opinions)"
            else:
                continue
                
            reqs = int(row.get("Request Count", "0"))
            fails = int(row.get("Failure Count", "0"))
            avg_rt = float(row.get("Average Response Time", "0"))
            max_rt = float(row.get("Max Response Time", "0"))
            rps = float(row.get("Requests/s", "0"))
            
            error_rate = (fails / reqs * 100) if reqs > 0 else 0.0
            
            metrics[key] = {
                "avg_rt": f"{avg_rt:.2f}",
                "max_rt": f"{max_rt:.0f}",
                "rps": f"{rps:.2f}",
                "error_rate": f"{error_rate:.2f}"
            }
    return metrics

def main():
    print(f"{Colors.OKCYAN}{Colors.BOLD}======================================================================={Colors.ENDC}")
    print(f"{Colors.OKCYAN}{Colors.BOLD} 🚀 性能压测多场景遍历套件启动 (Multi-Scenario Load Test) {Colors.ENDC}")
    print(f"{Colors.OKCYAN}{Colors.BOLD}======================================================================={Colors.ENDC}")

    report_file = SCRIPT_DIR.parent / "multi_scenario_performance_report.md"
    
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("# 舆情风控系统 - 性能压测多场景对比报告\n\n")
        f.write("> **压测环境说明**：在所有压测场景下，系统后台均有一条常驻线程在以极高频率执行“数据源抓取”入库操作，以此引发底层的 SQLite 读写锁竞争（Read-Write Collision）。\n\n")

    for scenario_idx, count in enumerate(SCENARIOS, 1):
        print(f"\n{Colors.HEADER}{'='*20} 正在执行场景 {scenario_idx}: {count} 条数据 {'='*20}{Colors.ENDC}")
        data_file_name = f"mock_data_{count}"
        
        print(f"{Colors.OKBLUE}[{count}级别] 1. 生成数据...{Colors.ENDC}")
        run_command([sys.executable, str(GENERATE_SCRIPT), "--count", str(count), "--output", data_file_name], cwd=ROOT_DIR)

        print(f"{Colors.OKBLUE}[{count}级别] 2. 刷入数据库...{Colors.ENDC}")
        loader_script = write_db_loader_script(data_file_name)
        run_command([sys.executable, str(loader_script)])
        os.remove(loader_script)

        server_process = None
        col_proc = None

        try:
            print(f"{Colors.OKBLUE}[{count}级别] 3. 启动后台服务...{Colors.ENDC}")
            os.environ["no_proxy"] = "*"
            os.environ["NO_PROXY"] = "*"
            server_process = run_command([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"], cwd=BACKEND_DIR, wait=False)
            print(f"{Colors.OKBLUE}[{count}级别] 3.1 等待服务完全启动 (15秒)...{Colors.ENDC}")
            time.sleep(15)

            print(f"{Colors.OKBLUE}[{count}级别] 4. 启动系统后台“数据源抓取”干扰...{Colors.ENDC}")
            collision_script = SCRIPT_DIR / "temp_collision.py"
            with open(collision_script, "w", encoding="utf-8") as f:
                f.write(f"""import requests, time, threading
def poke():
    for _ in range(50):
        try:
            requests.post("http://127.0.0.1:8000/api/import/demo", timeout=2)
        except:
            pass
        time.sleep(1)
threads = [threading.Thread(target=poke) for _ in range(2)]
for t in threads: t.start()
""")
            col_proc = run_command([sys.executable, str(collision_script)], wait=False)

            print(f"{Colors.WARNING}[{count}级别] 5. 执行 Locust 压测 ({USERS}并发, {RUN_TIME})...{Colors.ENDC}")
            results_prefix = str(SCRIPT_DIR.parent / "results" / f"multi_perf_{count}")
            os.makedirs(os.path.dirname(results_prefix), exist_ok=True)
            
            locust_cmd = [
                "locust", "-f", str(LOCUST_FILE),
                "--host=http://127.0.0.1:8000",
                "--headless", "-u", str(USERS), "-r", str(SPAWN_RATE),
                "--run-time", RUN_TIME,
                f"--csv={results_prefix}"
            ]
            run_command(locust_cmd)
            
            print(f"{Colors.OKBLUE}[{count}级别] 7. 提取指标并写入报告...{Colors.ENDC}")
            stats_file = f"{results_prefix}_stats.csv"
            metrics = parse_metrics(stats_file)
            
            with open(report_file, "a", encoding="utf-8") as f:
                f.write(f"## 【场景{scenario_idx}】数据规模：{count}条数据\n\n")
                modules_order = ["工作台轮询 (GET /api/dashboard/summary)", "舆情交叉检索 (GET /api/opinions)"]
                
                for i, mod_name in enumerate(modules_order, 1):
                    mod_data = metrics.get(mod_name, {"avg_rt": "N/A", "max_rt": "N/A", "rps": "N/A", "error_rate": "N/A"})
                    f.write(f"### 【测试的模块{i}】{mod_name}\n")
                    f.write(f"* **指标一：响应时间 (Response Time)**：Avg {mod_data['avg_rt']} ms, Max {mod_data['max_rt']} ms\n")
                    f.write(f"* **指标二：吞吐量 (Throughput)**：{mod_data['rps']} RPS\n")
                    f.write(f"* **指标三：并发用户数 (Concurrency)**：{USERS}\n")
                    f.write(f"* **指标四：错误率 (Error Rate)**：{mod_data['error_rate']}%\n\n")
                
                f.write("---\n\n")
            
            print(f"{Colors.OKGREEN}✅ 场景 {scenario_idx} 完成。{Colors.ENDC}")
            
        finally:
            print(f"{Colors.OKBLUE}[{count}级别] 6. 清理后台服务...{Colors.ENDC}")
            if server_process:
                if os.name == 'nt':
                    os.system(f"taskkill /F /T /PID {server_process.pid} >nul 2>&1")
                else:
                    server_process.terminate()
            if col_proc:
                if os.name == 'nt':
                    os.system(f"taskkill /F /T /PID {col_proc.pid} >nul 2>&1")
                else:
                    col_proc.terminate()
        
    print(f"\n{Colors.OKCYAN}{Colors.BOLD}======================================================================={Colors.ENDC}")
    print(f"{Colors.OKGREEN}🎉 所有压测场景执行完毕！综合报告已生成至: {report_file}{Colors.ENDC}")
    print(f"{Colors.OKCYAN}{Colors.BOLD}======================================================================={Colors.ENDC}")

if __name__ == "__main__":
    main()
