import uvicorn

from app.config import get_settings


if __name__ == "__main__":
    s = get_settings()
    print("=" * 50)
    print("  案件归档系统 V6 Web")
    print("=" * 50)
    print("  后端地址: http://{}:{}".format(s.host, s.port))
    print("  前端页面: http://{}:{}".format(s.host, s.port))
    print("  API:      http://{}:{}/api/health".format(s.host, s.port))
    print("  运行模式: {}".format(s.capabilities["mode"]))
    print("  首次使用: 在工作站本机双击启动入口，创建管理员")
    print("  外部 AI: {}".format("已允许" if s.allow_external_ai else "已禁止"))
    print("=" * 50)
    uvicorn.run("app.main:app", host=s.host, port=s.port, reload=False, workers=1, access_log=False)
