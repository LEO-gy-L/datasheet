@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo  Datasheet RAG 后端服务启动中……
echo  启动后浏览器开 http://127.0.0.1:8000/docs 看接口文档并可直接提问
echo  聊天界面：另开一个终端，cd frontend 后执行 npm run dev
echo  关闭本窗口即停止服务
echo ============================================
echo.
.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
pause
