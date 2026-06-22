import httpx
import sys
import time
import json

BASE_URL = "http://localhost:8000"

def print_divider(title):
    print(f"\n{'='*20} {title} {'='*20}")

def main():
    print_divider("02: 测试手动抓取数据源")
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        # 1. Login
        print(">>> 正在以系统管理员身份尝试登录...")
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        if resp.status_code != 200:
            print(f"[错误] 登录失败 ({resp.status_code}): {resp.text}")
            sys.exit(1)
        print("[成功] 登录成功，准备获取数据源列表\n")

        # 2. Get data sources
        print(">>> 正在拉取数据源列表...")
        print(f"    请求接口: GET {BASE_URL}/api/datasources")
        resp = client.get("/api/datasources")
        print(f"    响应状态码: {resp.status_code}")
        if resp.status_code != 200:
            print(f"[错误] 获取数据源列表失败: {resp.text}")
            sys.exit(1)
            
        datasources = resp.json()
        print(f"    当前系统中共有 {len(datasources)} 个数据源。")
        
        target_codes = ["test_weibo_source", "test_rss_source"]
        targets = [ds for ds in datasources if ds["code"] in target_codes]

        if not targets:
            print("[错误] 没有找到目标数据源(test_weibo_source 或 test_rss_source)，请先运行 01_add_datasources.py")
            sys.exit(1)
            
        print(f"    成功匹配到 {len(targets)} 个测试目标数据源。即将开始逐个抓取...\n")

        # 3. Fetch targets
        for idx, ds in enumerate(targets, 1):
            print_divider(f"任务 {idx}/{len(targets)}: 抓取 {ds['name']}")
            print(f"    数据源 ID: {ds['id']}")
            print(f"    数据源类型: {ds['source_type']}")
            print(f"    请求 URL: {ds['url']}")
            
            print(f"\n    [操作] 正在触发抓取接口: POST {BASE_URL}/api/datasources/{ds['id']}/fetch ...")
            start_time = time.time()
            fetch_resp = client.post(f"/api/datasources/{ds['id']}/fetch")
            cost_time = time.time() - start_time
            
            print(f"    [返回] 响应状态码: {fetch_resp.status_code} (耗时: {cost_time:.2f}s)")
            
            if fetch_resp.status_code == 200:
                result = fetch_resp.json()
                print("    [完成] 解析的详细结果如下:")
                print(json.dumps(result, indent=4, ensure_ascii=False))
                print(f"\n    >> 总结: 状态为 {result.get('status')}")
                print(f"    >> 本次新增 {result.get('accepted')} 条数据，发现重复 {result.get('duplicate')} 条数据，拒绝 {result.get('rejected')} 条。")
                if result.get("errors"):
                    print(f"    [警告] 遇到部分错误: {result['errors']}")
            else:
                print(f"    [失败/拦截] 接口返回异常:")
                try:
                    error_json = fetch_resp.json()
                    print(json.dumps(error_json, indent=4, ensure_ascii=False))
                except Exception:
                    print(fetch_resp.text)
            
            time.sleep(1) # 稍微停顿一下
            
    print_divider("测试结束")

if __name__ == "__main__":
    main()
