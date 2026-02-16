@echo off
title OpenClaw - Post Frame Building Designer
cd /d "%~dp0"

if not exist ".env" (
    echo WARNING: .env file not found!
    echo Copy .env.example to .env and add your API keys.
    echo.
)

python main.py
pause
