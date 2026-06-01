@echo off
echo Starting...
docker compose up -d --build
start ngrok http 8080
echo Ready
pause
docker compose down