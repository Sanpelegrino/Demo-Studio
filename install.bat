@echo off
setlocal EnableDelayedExpansion

cd /d "%~dp0"

set "PG_USER=demo_studio"
set "PG_PASS=demo_local_dev"
set "PG_DB=demo_studio"
set "PORT=3777"

echo.
echo +======================================+
echo ^|       Demo Studio Installer          ^|
echo +======================================+
echo.

:: ─── 1. Check/Install winget ─────────────────────────────
where winget >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Installing winget ^(App Installer^)...
    powershell -NoProfile -Command "Add-AppxPackage -RegisterByFamilyName -MainPackage Microsoft.DesktopAppInstaller_8wekyb3d8bbwe" >nul 2>&1
    where winget >nul 2>&1
    if !errorlevel! neq 0 (
        echo [FAIL] Could not install winget automatically.
        echo        Install "App Installer" from the Microsoft Store, then re-run this script.
        exit /b 1
    )
)
echo [OK] winget available.

:: ─── 2. Check/Install Python ─────────────────────────────
set "PYTHON_OK=0"
python --version >nul 2>&1 && (
    for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do (
        for /f "tokens=1,2 delims=." %%a in ("%%v") do (
            if %%a GEQ 3 if %%b GEQ 10 set "PYTHON_OK=1"
        )
    )
)

if "!PYTHON_OK!"=="0" (
    echo [INFO] Installing Python 3.12 via winget...
    winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements --silent
    if !errorlevel! neq 0 (
        echo [FAIL] Python installation failed.
        echo        Install Python 3.12+ from https://www.python.org/downloads/ and re-run.
        exit /b 1
    )
    call :refresh_path
)

python --version >nul 2>&1 || (
    echo [FAIL] Python not found on PATH after install.
    echo        Close this terminal, open a new one, and re-run install.bat.
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo [OK] %%v

:: ─── 3. Check/Install PostgreSQL ─────────────────────────
where psql >nul 2>&1
if %errorlevel% neq 0 (
    :: Check default install location (newest first)
    if exist "C:\Program Files\PostgreSQL\17\bin\psql.exe" (
        set "PATH=%PATH%;C:\Program Files\PostgreSQL\17\bin"
    ) else if exist "C:\Program Files\PostgreSQL\16\bin\psql.exe" (
        set "PATH=%PATH%;C:\Program Files\PostgreSQL\16\bin"
    ) else if exist "C:\Program Files\PostgreSQL\15\bin\psql.exe" (
        set "PATH=%PATH%;C:\Program Files\PostgreSQL\15\bin"
    ) else (
        echo [INFO] Installing PostgreSQL via winget...
        winget install PostgreSQL.PostgreSQL.17 --accept-source-agreements --accept-package-agreements --silent
        if !errorlevel! neq 0 (
            echo [FAIL] PostgreSQL installation failed.
            echo        Install PostgreSQL 16 from https://www.postgresql.org/download/windows/
            echo        Then re-run this script.
            exit /b 1
        )
        call :refresh_path
        set "PATH=!PATH!;C:\Program Files\PostgreSQL\17\bin"
    )
)

where psql >nul 2>&1 || (
    echo [FAIL] psql not found on PATH.
    echo        Add PostgreSQL bin directory to your PATH and re-run.
    exit /b 1
)
for /f "tokens=*" %%v in ('psql --version 2^>^&1') do echo [OK] %%v

:: ─── 4. Start PostgreSQL Service ─────────────────────────
pg_isready -h 127.0.0.1 -p 5432 >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Starting PostgreSQL service...
    net start postgresql-x64-17 >nul 2>&1 || (
        net start postgresql-x64-16 >nul 2>&1 || (
            net start postgresql-x64-15 >nul 2>&1 || (
                sc start postgresql-x64-17 >nul 2>&1
            )
        )
    )
    :: Wait up to 15 seconds
    for /L %%i in (1,1,15) do (
        pg_isready -h 127.0.0.1 -p 5432 >nul 2>&1 && goto :pg_running
        timeout /t 1 /nobreak >nul
    )
    echo [FAIL] PostgreSQL did not start.
    echo        Start the PostgreSQL service manually and re-run this script.
    exit /b 1
)
:pg_running
echo [OK] PostgreSQL is running.

:: ─── 5. Create Database and User ─────────────────────────
:: Try authenticating as postgres superuser
set "PG_SUPERPASS="
set "PG_AUTH_OK=0"

for %%P in ("" "postgres" "password") do (
    if "!PG_AUTH_OK!"=="0" (
        set "PGPASSWORD=%%~P"
        psql -U postgres -h 127.0.0.1 -c "SELECT 1" >nul 2>&1
        if !errorlevel! equ 0 (
            set "PG_SUPERPASS=%%~P"
            set "PG_AUTH_OK=1"
        )
    )
)

if "!PG_AUTH_OK!"=="0" (
    echo.
    set /p "PG_SUPERPASS=Enter your PostgreSQL 'postgres' superuser password: "
    set "PGPASSWORD=!PG_SUPERPASS!"
    psql -U postgres -h 127.0.0.1 -c "SELECT 1" >nul 2>&1 || (
        echo [FAIL] Cannot authenticate to PostgreSQL as 'postgres'.
        echo        Verify your PostgreSQL superuser password and re-run.
        exit /b 1
    )
)

set "PGPASSWORD=!PG_SUPERPASS!"

:: Create role if not exists
psql -U postgres -h 127.0.0.1 -c "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '%PG_USER%') THEN CREATE ROLE %PG_USER% WITH LOGIN PASSWORD '%PG_PASS%'; END IF; END $$;" >nul 2>&1
if %errorlevel% neq 0 (
    echo [FAIL] Could not create database user.
    exit /b 1
)

:: Create database if not exists
for /f "tokens=*" %%r in ('psql -U postgres -h 127.0.0.1 -tc "SELECT 1 FROM pg_database WHERE datname = '%PG_DB%'" 2^>nul') do set "DB_CHECK=%%r"
set "DB_CHECK=!DB_CHECK: =!"
if not "!DB_CHECK!"=="1" (
    psql -U postgres -h 127.0.0.1 -c "CREATE DATABASE %PG_DB% OWNER %PG_USER%;" >nul 2>&1
    if !errorlevel! neq 0 (
        echo [FAIL] Could not create database.
        exit /b 1
    )
)
echo [OK] Database '%PG_DB%' and user '%PG_USER%' ready.

:: Clear superuser password from environment
set "PGPASSWORD="

:: ─── 6. Python venv + Dependencies ───────────────────────
if not exist ".venv\Scripts\activate.bat" (
    echo [INFO] Creating virtual environment...
    python -m venv .venv
)
call .venv\Scripts\activate.bat
echo [INFO] Installing Python dependencies...
pip install --upgrade pip -q >nul 2>&1
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo [FAIL] pip install failed.
    exit /b 1
)
echo [OK] Python dependencies installed.

:: ─── 7. Configure .env ───────────────────────────────────
if exist .env (
    echo.
    set /p "OVERWRITE=.env already exists. Overwrite? [y/N]: "
    if /i "!OVERWRITE!" neq "y" (
        echo [OK] Keeping existing .env.
        goto :skip_env
    )
    del .env
)

echo.
set /p "AUTH_TOKEN=Enter your Anthropic bearer token: "
if "!AUTH_TOKEN!"=="" (
    echo [FAIL] Token cannot be empty.
    exit /b 1
)
copy .env.example .env >nul
powershell -NoProfile -Command "(Get-Content .env) -replace 'your-bedrock-bearer-token', '%AUTH_TOKEN%' | Set-Content .env"
echo [OK] .env configured.
:skip_env

:: ─── 8. Launch ───────────────────────────────────────────
echo.
echo ========================================
echo   Starting Demo Studio on port %PORT%...
echo   Press Ctrl+C to stop.
echo ========================================
echo.

:: Open browser after a short delay
start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:%PORT%"

python -m uvicorn app:app --host 0.0.0.0 --port %PORT%
goto :eof

:: ─── Subroutines ─────────────────────────────────────────

:refresh_path
:: Re-read PATH from registry (picks up installs without opening a new terminal)
for /f "tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "SYS_PATH=%%b"
for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "USR_PATH=%%b"
set "PATH=!SYS_PATH!;!USR_PATH!"
goto :eof
