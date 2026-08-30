@echo off
chcp 65001 >nul
title [VALORANT] 로컬 웹 대시보드 서버 실행기
cd /d "%~dp0"
echo ========================================================
echo  VALORANT 모바일 웹 대시보드 서버 (로컬 테스트 모드)
echo  접속 주소: http://localhost:8000
echo ========================================================
echo.
python -m pip install -r requirements.txt
echo.
echo [*] 웹 서버를 시작합니다... (종료하려면 Ctrl + C)
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
pause
