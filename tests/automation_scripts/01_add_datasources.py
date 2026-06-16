import httpx
import sys
import json

BASE_URL = "http://localhost:8000"

def print_divider(title):
    print(f"\n{'='*20} {title} {'='*20}")

def main():
    print_divider("01: 测试新增数据源表单")
    with httpx.Client(base_url=BASE_URL) as client:
        # 1. Login
        print(">>> 正在以系统管理员(admin)身份尝试登录...")
        print(f"    请求接口: POST {BASE_URL}/api/auth/login")
        print("    提交数据: {'username': 'admin', 'password': '***'}")
        resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        print(f"    响应状态码: {resp.status_code}")
        if resp.status_code != 200:
            print(f"[错误] 登录失败: {resp.text}")
            sys.exit(1)
        print("[成功] 登录完毕，已获取 Cookie\n")

        # 2. Add Weibo source
        print_divider("正在添加 [微博] 数据源")
        weibo_data = {
            "code": "test_weibo_source",
            "name": "测试微博数据源",
            "source_type": "weibo",
            "url": "http://localhost:8000/static/demo_opinions.json", 
            "weight": 1.0,
            "is_enabled": True,
            "description": "自动化测试脚本创建的微博数据源"
        }
        print(f"    请求接口: POST {BASE_URL}/api/datasources")
        print(f"    提交表单内容:\n{json.dumps(weibo_data, indent=4, ensure_ascii=False)}")
        resp = client.post("/api/datasources", json=weibo_data)
        print(f"    响应状态码: {resp.status_code}")
        if resp.status_code == 201:
            print(f"[成功] 微博数据源添加成功！返回数据: \n{json.dumps(resp.json(), indent=4, ensure_ascii=False)}")
        elif resp.status_code == 409:
            print("[跳过] 系统提示：微博数据源(code: test_weibo_source)已存在 (HTTP 409)")
        else:
            print(f"[失败] 微博数据源添加失败: {resp.text}")
        print("")

        # 3. Add RSS source
        print_divider("正在添加 [RSS] 数据源")
        rss_data = {
            "code": "test_rss_source",
            "name": "测试 RSS 数据源",
            "source_type": "rss",
            "url": "https://rss.sina.com.cn/news/allnews/roll.xml",
            "weight": 1.5,
            "is_enabled": True,
            "description": "自动化测试脚本创建的新浪 RSS 数据源"
        }
        print(f"    请求接口: POST {BASE_URL}/api/datasources")
        print(f"    提交表单内容:\n{json.dumps(rss_data, indent=4, ensure_ascii=False)}")
        resp = client.post("/api/datasources", json=rss_data)
        print(f"    响应状态码: {resp.status_code}")
        if resp.status_code == 201:
            print(f"[成功] RSS 数据源添加成功！返回数据: \n{json.dumps(resp.json(), indent=4, ensure_ascii=False)}")
        elif resp.status_code == 409:
            print("[跳过] 系统提示：RSS 数据源(code: test_rss_source)已存在 (HTTP 409)")
        else:
            print(f"[失败] RSS 数据源添加失败: {resp.text}")

    print_divider("测试结束")

if __name__ == "__main__":
    main()
