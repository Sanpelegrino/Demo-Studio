@echo off
setlocal EnableDelayedExpansion

cd /d "%~dp0"

set "PORT=3777"

if not exist ".venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found. Run install.bat first.
    exit /b 1
)
if not exist ".env" (
    echo ERROR: .env not found. Run install.bat first.
    exit /b 1
)

:: Ensure Postgres bin is on PATH
if exist "C:\Program Files\PostgreSQL\17\bin\psql.exe" set "PATH=%PATH%;C:\Program Files\PostgreSQL\17\bin"
if exist "C:\Program Files\PostgreSQL\16\bin\psql.exe" set "PATH=%PATH%;C:\Program Files\PostgreSQL\16\bin"
if exist "C:\Program Files\PostgreSQL\15\bin\psql.exe" set "PATH=%PATH%;C:\Program Files\PostgreSQL\15\bin"

:: Ensure Postgres is running
pg_isready -h 127.0.0.1 -p 5432 >nul 2>&1
if %errorlevel% neq 0 (
    echo Starting PostgreSQL...
    net start postgresql-x64-17 >nul 2>&1 || net start postgresql-x64-16 >nul 2>&1 || net start postgresql-x64-15 >nul 2>&1
    timeout /t 2 /nobreak >nul
    pg_isready -h 127.0.0.1 -p 5432 >nul 2>&1 || (
        echo ERROR: PostgreSQL is not running. Start it manually and try again.
        exit /b 1
    )
)

call .venv\Scripts\activate.bat

echo Starting Demo Studio on http://localhost:%PORT% ...
echo Press Ctrl+C to stop.
echo.

start "" cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:%PORT%"

python -m uvicorn app:app --host 0.0.0.0 --port %PORT%
