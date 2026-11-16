@echo off
setlocal

docker ps >nul 2>&1
if errorlevel 1 (
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    :waitdocker
    timeout /t 3 /nobreak >nul
    docker ps >nul 2>&1
    if errorlevel 1 goto waitdocker
)

docker compose --profile dev down dev
docker compose --profile dev up -d dev

set "COMMIT="
for /f "skip=1 delims=" %%A in ('code --version 2^>nul') do (
    if not defined COMMIT set "COMMIT=%%A"
)

if not defined COMMIT (
    echo Could not read the VS Code commit from "code --version".
    pause
    exit /b 1
)

echo Using VS Code commit %COMMIT%

docker exec autocompression-dev-1 sh -c "test -x /root/.vscode-server/bin/%COMMIT%/bin/code-server || (rm -rf /root/.vscode-server/bin/%COMMIT% && mkdir -p /root/.vscode-server/bin/%COMMIT% && curl -fL https://update.code.visualstudio.com/commit:%COMMIT%/server-linux-x64/stable | tar -xz --strip-components 1 -C /root/.vscode-server/bin/%COMMIT%)"
docker exec autocompression-dev-1 sh -c "S=/root/.vscode-server/bin/%COMMIT%/bin/code-server; for e in ms-python.python ms-python.debugpy ms-python.vscode-pylance ms-python.vscode-python-envs; do $S --install-extension $e; done"
pause