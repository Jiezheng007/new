import requests
import time
import os
import sys
import subprocess
import json
from pathlib import Path

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
    print("=" * 60)
    print(" 🚀 数据抓取写入专项压测 (Payload Scalability) 启动")
    print("=" * 60)

    # 1. 启动服务
    print("\n[1/4] 启动后台服务并预热...")
    server_process = run_command([sys.executable, "-m", "uvicorn", "app.main:app"], cwd=BACKEND_DIR, wait=False)
    time.sleep(5)

    try:
        # 2. 登录获取 Token
        print("[2/4] 获取 Admin Token...")
        login_res = requests.post("http://127.0.0.1:8000/api/auth/login", json={"username": "admin", "password": "admin123"})
        if login_res.status_code != 200:
            print("登录失败:", login_res.text)
            sys.exit(1)
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 3. 压测不同体量的 Payload
        print("\n[3/4] 开始推送不同规模的 Payload...\n")
        results = []

        for count in SCENARIOS:
            print(f"  -> 测试 {count} 条记录...")
            payload_str = generate_payload(count)
            
            t0 = time.time()
            try:
                # 使用 data= 上传表单字段
                res = requests.post("http://127.0.0.1:8000/api/import/json", headers=headers, data={"payload": payload_str}, timeout=30)
                t1 = time.time()
                elapsed_ms = (t1 - t0) * 1000
                
                if res.status_code == 200:
                    throughput = int(count / (elapsed_ms / 1000))
                    status_text = "正常"
                else:
                    throughput = 0
                    status_text = f"失败 (HTTP {res.status_code})"
                    print(f"     ! 报错: {res.text}")
                    
            except requests.exceptions.RequestException as e:
                t1 = time.time()
                elapsed_ms = (t1 - t0) * 1000
                throughput = 0
                status_text = "失败 (Timeout/Connection Error)"
                print(f"     ! 异常: {e}")

            results.append({
                "count": count,
                "elapsed_ms": f"{elapsed_ms:.0f}" if status_text == "正常" else "N/A",
                "throughput": throughput,
                "status": status_text
            })
            
            print(f"     结果: {status_text}, 耗时 {elapsed_ms:.0f} ms, 吞吐量 {throughput} R/s")
            time.sleep(2) # 给系统喘息时间

        # 4. 生成报告
        print("\n[4/4] 正在生成报告...")
        report_file = SCRIPT_DIR.parent / "ingestion_scalability_report.md"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write("# 数据源抓取写入模块 - 吞吐量专项压测\n\n")
            f.write("> **测试目的**：验证后端 `POST /api/import/json` 接口在单次接收极大体积 JSON 数据包（即数据洪峰）时的解析与批量落库吞吐能力。\n\n")
            f.write("| 数据包体量 (Records/Payload) | 接口响应时间 (ms) | 处理吞吐量 (Records/Sec) | 错误率 / 状态 |\n")
            f.write("|---|---|---|---|\n")
            for r in results:
                f.write(f"| {r['count']} 条 | {r['elapsed_ms']} ms | {r['throughput']} R/s | {r['status']} |\n")
        
        print(f"\n🎉 压测完成！专项报告已生成至: {report_file}")

    finally:
        print("\n🧹 清理后台服务...")
        if os.name == 'nt':
            os.system(f"taskkill /F /T /PID {server_process.pid} >nul 2>&1")
        else:
            server_process.terminate()

if __name__ == "__main__":
    main()
