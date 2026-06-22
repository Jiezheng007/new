from locust import HttpUser, task, between

class ExtremeUser(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self):
        # 登录获取 token
        res = self.client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        if res.status_code == 200:
            self.token = res.json().get("access_token")
        else:
            self.token = None

    @task(3)
    def get_opinions(self):
        if self.token:
            self.client.get("/api/opinions?skip=0&limit=50", 
                            headers={"Authorization": f"Bearer {self.token}"}, 
                            name="/api/opinions")

    @task(1)
    def get_dashboard(self):
        if self.token:
            self.client.get("/api/dashboard/summary", 
                            headers={"Authorization": f"Bearer {self.token}"}, 
                            name="/api/dashboard/summary")
