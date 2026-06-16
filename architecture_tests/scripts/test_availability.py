import pytest
from fastapi.testclient import TestClient

# 提示：运行此脚本需要确保你能从上一级目录导入后端的 app 实例。
# 如果执行报错找不到模块，请在后台项目根目录执行：pytest ../architecture_tests/scripts/test_availability.py
try:
    from app.main import app 
except ImportError:
    print("导入 app 失败，请确保你将 PYTHONPATH 指向了 backend 目录，或者将此文件移动到 backend/tests/ 目录下执行。")
    app = None

if app:
    client = TestClient(app)

def test_system_availability_when_nlp_fails(mocker):
    """
    【可用性测试用例】：故障注入
    场景：模拟外部的智能分析组件（或第三方API）发生超时。
    预期：系统能够优雅地捕获错误并继续运行，而不是引起服务奔溃导致调用方收到 500。
    """
    
    # 使用 mock 强制使 NLP 提供者的分析函数抛出异常
    # 假设后端的 NLP 提供者在这个位置：app.services.nlp.KeywordNlpProvider.analyze
    # (根据你们团队实际的代码路径进行调整)
    try:
        mock_nlp = mocker.patch(
            "app.services.nlp.KeywordNlpProvider.analyze", 
            side_effect=TimeoutError("模拟的外部API调用超时")
        )
    except AttributeError:
        # 如果路径不对，这里只是提供一个测试思路示范
        pytest.skip("请根据实际的后端代码结构调整 mocker.patch 的路径")
        
    # 触发一段通常会调用 NLP 分析的代码（例如，导入一条新的舆情或手动触发一条舆情的分析）
    # 这里以拉取演示数据为例
    response = client.post("/api/import/demo")
    
    # 【核心断言】
    # 我们不在乎这条数据是不是分析成功了，我们在乎的是系统不能挂！
    # 断言响应状态码不应该是 500 (Internal Server Error)
    assert response.status_code != 500, "可用性测试失败：依赖故障导致系统全局抛出了 500 错误"
    
    # 打印成功信息，作为测试报告的证据
    print("\n[通过] NLP依赖超时的情况下，系统成功拦截错误，避免了服务雪崩！")
