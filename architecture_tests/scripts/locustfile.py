from locust import HttpUser, task, between
import json

class RiskControlSystemUser(HttpUser):
    """
    性能压测脚本：使用 Locust 模拟用户行为
    
    运行方法：
    1. pip install locust
    2. 在当前目录下运行: locust -f locustfile.py --host=http://localhost:8000
    3. 打开浏览器访问 http://localhost:8089 设置并发数开始压测
    """
    wait_time = between(1, 3) # 用户执行每个任务之间的等待时间(1到3秒)
    
    def on_start(self):
        """用户开始运行前执行的操作，通常用于登录获取认证"""
        # 注意：此处使用 /api/auth/login，需确保后端已初始化 admin 账号
        response = self.client.post("/api/auth/login", json={
            "username": "admin",
            "password": "admin123"
        })
        if response.status_code != 200:
            print("登录失败，请检查账号密码或系统是否已启动")

    @task(3)
    def view_dashboard(self):
        """模拟高频操作：查看工作台统计数据 (权重 3)"""
        self.client.get("/api/dashboard")

    @task(2)
    def view_opinions(self):
        """模拟普通操作：翻页查看舆情列表 (权重 2)"""
        self.client.get("/api/opinions?page=1&size=20")

    @task(1)
    def generate_report(self):
        """
        模拟耗时操作：提交生成报告任务 (权重 1)
        此用例专门用于验证【性能与可用性】中的异步处理能力。
        响应时间必须极短，不能挂起等待报告生成。
        """
        self.client.post("/api/reports", json={
            "title": "性能压测期间的异步报告",
            "risk_level": "high"
        })
