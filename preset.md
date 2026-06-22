# 系统预设账号与权限说明

本项目的数据库在初始化（通过执行 [seed_data.py](file:///c:/Users/Zhang/Desktop/SA_hw/new/backend/scripts/seed_data.py) 或系统首次启动时调用 [bootstrap.py](file:///c:/Users/Zhang/Desktop/SA_hw/new/backend/app/services/bootstrap.py) 中的 `init_db` 函数）时，会自动创建以下预设账号，以便于对系统的不同功能和角色进行演示与测试。

## 预设账号列表

| 用户名 (Username) | 密码 (Password) | 显示姓名 (Full Name) | 角色代码 (Role Code) | 角色名称 (Role Name) | 角色描述 (Role Description) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`admin`** | `admin123` | Bootstrap Admin | `admin` | 系统管理员 | 负责用户、角色、数据源与风险规则管理。 |
| **`risk`** | `risk123` | 风控演示账号 | `risk_control` | 风控人员 | 负责舆情查看、预警确认、工单创建与报告生成。 |
| **`handler`** | `handler123` | 处置演示账号 | `handler` | 处置人员 | 负责处理分配给自己的工单。 |
| **`auditor`** | `auditor123` | 审计演示账号 | `auditor` | 审计人员 | 负责查看审计日志与关键操作。 |
| **`viewer`** | `viewer123` | 查看演示账号 | `viewer` | 普通查看人员 | 只读访问工作台和报告。 |

> [!NOTE]
> 以上账号及密码定义于 [bootstrap.py](file:///c:/Users/Zhang/Desktop/SA_hw/new/backend/app/services/bootstrap.py) 和 [config.py](file:///c:/Users/Zhang/Desktop/SA_hw/new/backend/app/core/config.py)。

---

## 各角色权限及菜单访问范围

角色权限与菜单访问范围定义在 [role_codes.py](file:///c:/Users/Zhang/Desktop/SA_hw/new/backend/app/models/role_codes.py) 中。

### 1. 系统管理员 (`admin`)
* **权限说明**: 拥有系统的所有操作权限 (`*`)。
* **访问菜单**:
  * 工作台 (`/web/workbench`)
  * 数据源管理 (`/web/datasources`)
  * 风险规则 (`/web/rules`)
  * 数据导入 (`/web/import`)
  * 舆情列表 (`/web/opinions`)
  * 预警中心 (`/web/alerts`)
  * 工单管理 (`/web/tickets`)
  * 报告中心 (`/web/reports`)
  * 用户与角色 (`/web/users`)
  * 审计日志 (`/web/audit`)

### 2. 风控人员 (`risk`)
* **权限说明**: 
  * 舆情: 查看 (`opinion:read`)、分析 (`opinion:analyze`)
  * 预警: 查看 (`alert:read`)、确认 (`alert:confirm`)、忽略 (`alert:ignore`)
  * 工单: 查看 (`ticket:read`)、创建 (`ticket:create`)、指派 (`ticket:assign`)、归档 (`ticket:archive`)
  * 报告: 创建 (`report:create`)、查看 (`report:read`)、下载 (`report:download`)
  * 数据源与规则: 只读查看 (`datasource:read`, `rule:read`)
  * 数据导入: 执行导入 (`import:run`)
* **访问菜单**:
  * 工作台 (`/web/workbench`)
  * 数据导入 (`/web/import`)
  * 舆情列表 (`/web/opinions`)
  * 预警中心 (`/web/alerts`)
  * 工单管理 (`/web/tickets`)
  * 报告中心 (`/web/reports`)

### 3. 处置人员 (`handler`)
* **权限说明**:
  * 工单: 只读查看分配给自己的工单 (`ticket:read:assigned`)、更新工单状态 (`ticket:update_status`)、完成工单 (`ticket:complete`)
* **访问菜单**:
  * 工作台 (`/web/workbench`)
  * 我的工单 (`/web/tickets`)

### 4. 审计人员 (`auditor`)
* **权限说明**:
  * 审计日志: 查看 (`audit:read`)
  * 舆情、预警、工单、报告、数据源: 只读查看权限 (`opinion:read`, `alert:read`, `ticket:read`, `report:read`, `datasource:read`)
* **访问菜单**:
  * 工作台 (`/web/workbench`)
  * 审计日志 (`/web/audit`)
  * 舆情列表 (`/web/opinions`)
  * 预警中心 (`/web/alerts`)
  * 工单管理 (`/web/tickets`)
  * 报告中心 (`/web/reports`)
  * 数据源管理 (`/web/datasources`)

### 5. 普通查看人员 (`viewer`)
* **权限说明**:
  * 工作台: 只读访问 (`dashboard:read`)
  * 舆情与报告: 只读查看 (`opinion:read`, `report:read`)
* **访问菜单**:
  * 工作台 (`/web/workbench`)
  * 报告中心 (`/web/reports`)

---

## 数据库初始化与数据填充

如果需要重置数据库或重新生成上述预设账号，可以在 `backend` 目录下运行：

```bash
# 运行数据库种子脚本重新填充数据
python scripts/seed_data.py
```

该脚本将完成以下初始化步骤：
1. 创建数据库表结构。
2. 注入预设角色和权限关系（[role_codes.py](file:///c:/Users/Zhang/Desktop/SA_hw/new/backend/app/models/role_codes.py)）。
3. 注入系统默认的风险评分规则阈值与关键词规则。
4. 注入内置的静态演示数据源和导入合并源。
5. 创建上述预设账号（如果不存在）。
