import requests
import time
import os
import sys
import subprocess
import json
from pathlib import Path

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

SCENARIOS = [100, 1000, 5000, 10000]

def run_command(cmd, cwd=None, wait=True):
    if wait:
        subprocess.run(cmd, cwd=cwd)
    else:
        return subprocess.Popen(cmd, cwd=cwd)

def generate_payload(count):
    records = []
    for i in range(count):
        records.append({
            "title": f"Scalability Test Title {count}-{i}",
            "content": f"Scalability Test Content. This is a unique item {count}-{i} to prevent hash collision.",
            "url": f"http://test.com/{count}/{i}",
            "author": "tester"
        })
    return json.dumps(records)

def main():
    print(f"{Colors.OKCYAN}{Colors.BOLD}======================================================================={Colors.ENDC}")
    print(f"{Colors.OKCYAN}{Colors.BOLD} 🚀 数据抓取写入专项压测 (Payload Scalability) 启动 {Colors.ENDC}")
    print(f"{Colors.OKCYAN}{Colors.BOLD}======================================================================={Colors.ENDC}")

    # 1. 启动服务
    print(f"\n{Colors.HEADER}[1/4]{Colors.ENDC} 启动后台服务并预热...")
    server_process = run_command([sys.executable, "-m", "uvicorn", "app.main:app"], cwd=BACKEND_DIR, wait=False)
    time.sleep(5)

    try:
        # 2. 登录获取 Token
        print(f"{Colors.HEADER}[2/4]{Colors.ENDC} 获取 Admin Token...")
        login_res = requests.post("http://127.0.0.1:8000/api/auth/login", json={"username": "admin", "password": "admin123"})
        if login_res.status_code != 200:
            print(f"{Colors.FAIL}登录失败: {login_res.text}{Colors.ENDC}")
            sys.exit(1)
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 3. 压测不同体量的 Payload
        print(f"\n{Colors.HEADER}[3/4]{Colors.ENDC} 开始推送不同规模的 Payload...\n")
        results = []

        for count in SCENARIOS:
            print(f"  {Colors.OKBLUE}-> 测试 {count} 条记录...{Colors.ENDC}")
            payload_str = generate_payload(count)
            
            t0 = time.time()
            try:
                # 使用 data= 上传表单字段
                res = requests.post("http://127.0.0.1:8000/api/import/json", headers=headers, data={"payload": payload_str}, timeout=30)
                t1 = time.time()
                elapsed_ms = (t1 - t0) * 1000
                
                if res.status_code == 200:
                    throughput = int(count / (elapsed_ms / 1000))
                    status_text = f"{Colors.OKGREEN}正常{Colors.ENDC}"
                else:
                    throughput = 0
                    status_text = f"{Colors.FAIL}失败 (HTTP {res.status_code}){Colors.ENDC}"
                    print(f"     {Colors.FAIL}! 报错: {res.text}{Colors.ENDC}")
                    
            except requests.exceptions.RequestException as e:
                t1 = time.time()
                elapsed_ms = (t1 - t0) * 1000
                throughput = 0
                status_text = f"{Colors.FAIL}失败 (Timeout/Connection Error){Colors.ENDC}"
                print(f"     {Colors.FAIL}! 异常: {e}{Colors.ENDC}")

            results.append({
                "count": count,
                "elapsed_ms": f"{elapsed_ms:.0f}" if "正常" in status_text else "N/A",
                "throughput": throughput,
                "status": "正常" if "正常" in status_text else "失败"
            })
            
            # 颜色渲染
            t_color = Colors.OKGREEN if throughput > 1000 else Colors.WARNING
            print(f"     {Colors.BOLD}结果: {status_text}, 耗时 {elapsed_ms:.0f} ms, 吞吐量 {t_color}{throughput} R/s{Colors.ENDC}")
            time.sleep(2) # 给系统喘息时间

        # 4. 生成报告
        print(f"\n{Colors.HEADER}[4/4]{Colors.ENDC} 正在生成报告...")
        report_file = SCRIPT_DIR.parent / "ingestion_scalability_report.md"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write("# 数据源抓取写入模块 - 吞吐量专项压测\n\n")
            f.write("> **测试目的**：验证后端 `POST /api/import/json` 接口在单次接收极大体积 JSON 数据包（即数据洪峰）时的解析与批量落库吞吐能力。\n\n")
            f.write("| 数据包体量 (Records/Payload) | 接口响应时间 (ms) | 处理吞吐量 (Records/Sec) | 错误率 / 状态 |\n")
            f.write("|---|---|---|---|\n")
            for r in results:
                f.write(f"| {r['count']} 条 | {r['elapsed_ms']} ms | {r['throughput']} R/s | {r['status']} |\n")
        
        print(f"\n{Colors.OKCYAN}{Colors.BOLD}======================================================================={Colors.ENDC}")
        print(f"{Colors.OKGREEN}🎉 压测完成！专项报告已生成至: {report_file}{Colors.ENDC}")
        print(f"{Colors.OKCYAN}{Colors.BOLD}======================================================================={Colors.ENDC}")

    finally:
        print(f"\n{Colors.WARNING}🧹 清理后台服务...{Colors.ENDC}")
        if os.name == 'nt':
            os.system(f"taskkill /F /T /PID {server_process.pid} >nul 2>&1")
        else:
            server_process.terminate()

if __name__ == "__main__":
    main()
