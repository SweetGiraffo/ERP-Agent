@echo off
cd /d "%~dp0"

if not exist .env (
    if exist ..\.env (
        copy ..\.env .env
        echo Copied .env from parent directory
    )
)

if not exist .env (
    echo ⚠️  .env file not found. Create one from .env.example
    exit /b 1
)

echo Starting Flask dashboard...
python app.py
pause
