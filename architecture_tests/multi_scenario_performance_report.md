# 舆情风控系统 - 性能压测多场景对比报告

> **压测环境说明**：在所有压测场景下，系统后台均有一条常驻线程在以极高频率执行“数据源抓取”入库操作，以此引发底层的 SQLite 读写锁竞争（Read-Write Collision）。

## 【场景1】数据规模：10000条数据

### 【测试的模块1】工作台轮询 (GET /api/dashboard/summary)
* **指标一：响应时间 (Response Time)**：Avg 34001.74 ms, Max 37009 ms
* **指标二：吞吐量 (Throughput)**：0.84 RPS
* **指标三：并发用户数 (Concurrency)**：100
* **指标四：错误率 (Error Rate)**：0.00%

### 【测试的模块2】舆情交叉检索 (GET /api/opinions)
* **指标一：响应时间 (Response Time)**：Avg 9074.10 ms, Max 29460 ms
* **指标二：吞吐量 (Throughput)**：4.46 RPS
* **指标三：并发用户数 (Concurrency)**：100
* **指标四：错误率 (Error Rate)**：0.00%

---

## 【场景2】数据规模：100000条数据

### 【测试的模块1】工作台轮询 (GET /api/dashboard/summary)
* **指标一：响应时间 (Response Time)**：Avg 35754.88 ms, Max 37956 ms
* **指标二：吞吐量 (Throughput)**：0.71 RPS
* **指标三：并发用户数 (Concurrency)**：100
* **指标四：错误率 (Error Rate)**：0.00%

### 【测试的模块2】舆情交叉检索 (GET /api/opinions)
* **指标一：响应时间 (Response Time)**：Avg 10990.61 ms, Max 33107 ms
* **指标二：吞吐量 (Throughput)**：3.87 RPS
* **指标三：并发用户数 (Concurrency)**：100
* **指标四：错误率 (Error Rate)**：0.00%

---

## 【场景3】数据规模：200000条数据

### 【测试的模块1】工作台轮询 (GET /api/dashboard/summary)
* **指标一：响应时间 (Response Time)**：Avg 33875.85 ms, Max 37061 ms
* **指标二：吞吐量 (Throughput)**：0.76 RPS
* **指标三：并发用户数 (Concurrency)**：100
* **指标四：错误率 (Error Rate)**：0.00%

### 【测试的模块2】舆情交叉检索 (GET /api/opinions)
* **指标一：响应时间 (Response Time)**：Avg 9068.41 ms, Max 30418 ms
* **指标二：吞吐量 (Throughput)**：4.42 RPS
* **指标三：并发用户数 (Concurrency)**：100
* **指标四：错误率 (Error Rate)**：0.00%

---

