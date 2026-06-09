class RoleCode:
    ADMIN = "admin"
    RISK_CONTROL = "risk_control"
    HANDLER = "handler"
    AUDITOR = "auditor"
    VIEWER = "viewer"


ROLE_PERMISSIONS: dict[str, list[str]] = {
    RoleCode.ADMIN: ["*"],
    RoleCode.RISK_CONTROL: [
        "opinion:read", "opinion:analyze",
        "alert:read", "alert:confirm", "alert:ignore",
        "ticket:read", "ticket:create", "ticket:assign", "ticket:archive",
        "report:create", "report:read", "report:download",
        "datasource:read", "rule:read", "import:run",
    ],
    RoleCode.HANDLER: [
        "ticket:read:assigned", "ticket:update_status", "ticket:complete",
    ],
    RoleCode.AUDITOR: [
        "audit:read", "opinion:read", "alert:read", "ticket:read", "report:read",
    ],
    RoleCode.VIEWER: [
        "dashboard:read", "opinion:read", "report:read",
    ],
}


ROLE_NAV_ITEMS: dict[str, list[dict]] = {
    RoleCode.ADMIN: [
        {"key": "workbench", "label": "工作台", "href": "/web/workbench"},
        {"key": "datasources", "label": "数据源管理", "href": "/web/datasources"},
        {"key": "rules", "label": "风险规则", "href": "/web/rules"},
        {"key": "import", "label": "数据导入", "href": "/web/import"},
        {"key": "opinions", "label": "舆情列表", "href": "/web/opinions"},
        {"key": "alerts", "label": "预警中心", "href": "/web/alerts"},
        {"key": "tickets", "label": "工单管理", "href": "/web/tickets"},
        {"key": "reports", "label": "报告中心", "href": "/web/reports"},
        {"key": "users", "label": "用户与角色", "href": "/web/users"},
        {"key": "audit", "label": "审计日志", "href": "/web/audit"},
    ],
    RoleCode.RISK_CONTROL: [
        {"key": "workbench", "label": "工作台", "href": "/web/workbench"},
        {"key": "import", "label": "数据导入", "href": "/web/import"},
        {"key": "opinions", "label": "舆情列表", "href": "/web/opinions"},
        {"key": "alerts", "label": "预警中心", "href": "/web/alerts"},
        {"key": "tickets", "label": "工单管理", "href": "/web/tickets"},
        {"key": "reports", "label": "报告中心", "href": "/web/reports"},
    ],
    RoleCode.HANDLER: [
        {"key": "workbench", "label": "工作台", "href": "/web/workbench"},
        {"key": "tickets", "label": "我的工单", "href": "/web/tickets"},
    ],
    RoleCode.AUDITOR: [
        {"key": "workbench", "label": "工作台", "href": "/web/workbench"},
        {"key": "audit", "label": "审计日志", "href": "/web/audit"},
        {"key": "opinions", "label": "舆情列表", "href": "/web/opinions"},
        {"key": "alerts", "label": "预警中心", "href": "/web/alerts"},
        {"key": "tickets", "label": "工单管理", "href": "/web/tickets"},
        {"key": "datasources", "label": "数据源管理", "href": "/web/datasources"},
    ],
    RoleCode.VIEWER: [
        {"key": "workbench", "label": "工作台", "href": "/web/workbench"},
    ],
}


ROLE_SEEDS = [
    (RoleCode.ADMIN, "系统管理员", "负责用户、角色、数据源与风险规则管理"),
    (RoleCode.RISK_CONTROL, "风控人员", "负责舆情查看、预警确认、工单创建与报告生成"),
    (RoleCode.HANDLER, "处置人员", "负责处理分配给自己的工单"),
    (RoleCode.AUDITOR, "审计人员", "负责查看审计日志与关键操作"),
    (RoleCode.VIEWER, "普通查看人员", "只读访问工作台和报告"),
]
