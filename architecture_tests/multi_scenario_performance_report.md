# 舆情风控系统 - 性能压测多场景对比报告

> **压测环境说明**：在所有压测场景下，系统后台均有一条常驻线程在以极高频率执行“数据源抓取”入库操作，以此引发底层的 SQLite 读写锁竞争（Read-Write Collision）。

## 【场景1】数据规模：10000条数据

### 【测试的模块1】工作台轮询 (GET /api/dashboard/summary)
* **指标一：响应时间 (Response Time)**：Avg 1769.62 ms, Max 5476 ms
* **指标二：吞吐量 (Throughput)**：8.55 RPS
* **指标三：并发用户数 (Concurrency)**：100
* **指标四：错误率 (Error Rate)**：0.00%

### 【测试的模块2】舆情交叉检索 (GET /api/opinions)
* **指标一：响应时间 (Response Time)**：Avg 2368.52 ms, Max 3512 ms
* **指标二：吞吐量 (Throughput)**：27.37 RPS
* **指标三：并发用户数 (Concurrency)**：100
* **指标四：错误率 (Error Rate)**：0.00%

---

## 【场景2】数据规模：100000条数据

### 【测试的模块1】工作台轮询 (GET /api/dashboard/summary)
* **指标一：响应时间 (Response Time)**：Avg 2237.67 ms, Max 7383 ms
* **指标二：吞吐量 (Throughput)**：8.22 RPS
* **指标三：并发用户数 (Concurrency)**：100
* **指标四：错误率 (Error Rate)**：0.00%

### 【测试的模块2】舆情交叉检索 (GET /api/opinions)
* **指标一：响应时间 (Response Time)**：Avg 2404.72 ms, Max 3840 ms
* **指标二：吞吐量 (Throughput)**：26.09 RPS
* **指标三：并发用户数 (Concurrency)**：100
* **指标四：错误率 (Error Rate)**：0.00%

---

## 【场景3】数据规模：200000条数据

### 【测试的模块1】工作台轮询 (GET /api/dashboard/summary)
* **指标一：响应时间 (Response Time)**：Avg 1795.34 ms, Max 6656 ms
* **指标二：吞吐量 (Throughput)**：8.53 RPS
* **指标三：并发用户数 (Concurrency)**：100
* **指标四：错误率 (Error Rate)**：0.00%

### 【测试的模块2】舆情交叉检索 (GET /api/opinions)
* **指标一：响应时间 (Response Time)**：Avg 2510.68 ms, Max 3744 ms
* **指标二：吞吐量 (Throughput)**：25.94 RPS
* **指标三：并发用户数 (Concurrency)**：100
* **指标四：错误率 (Error Rate)**：0.00%

---

