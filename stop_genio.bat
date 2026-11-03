@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Genio를 끕니다...
docker compose down
pause
