@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  Datasheet RAG 后端服务启动中……
echo  启动后请打开项目根目录的 index.html 使用界面
echo  （地址：http://127.0.0.1:8000 ，接口文档 /docs）
echo  关闭本窗口即停止服务
echo ============================================
echo.
.venv\Scripts\python.exe -m uvicorn src.api:app --host 127.0.0.1 --port 8000
pause
