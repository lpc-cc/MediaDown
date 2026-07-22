@echo off
cd /d D:\123\555\backend
echo [%date% %time%] Starting... >> D:\123\555\launcher.log
start /min "" D:\123\python\pythonw.exe app.py
echo [%date% %time%] pythonw launched >> D:\123\555\launcher.log
ping -n 6 127.0.0.1 >nul
echo [%date% %time%] Opening browser >> D:\123\555\launcher.log
start http://localhost:5000
