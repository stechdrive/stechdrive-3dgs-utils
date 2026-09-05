@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

echo [INFO] setup_windows.bat

set "PYTHON_CMD="
set "PY_VER="
set "PY_VER_FULL="
set "PAUSE_ON_EXIT=1"
set "FORCE_SETUP=0"
set "CHECK_ARGS=--require-python 3.12"
set "UPDATE_ARGS=--candidates 3.12 --skip-pytest --locked"
set "SETUP_RESULT="
set "FFMPEG_SETUP_RESULT="
set "EXIT_CODE=0"
set "PYTHONUTF8=1"
set "PIP_DISABLE_PIP_VERSION_CHECK=1"
set "PY312_LOCAL=%LocalAppData%\Programs\Python\Python312\python.exe"
set "PY312_PROGRAMFILES=%ProgramFiles%\Python312\python.exe"
set "PY312_PROGRAMFILES_X86=%ProgramFiles(x86)%\Python312\python.exe"

:parse_args
if "%~1"=="" goto :main
if /I "%~1"=="--no-pause" (
    set "PAUSE_ON_EXIT=0"
    shift
    goto :parse_args
)
if /I "%~1"=="--pause" (
    set "PAUSE_ON_EXIT=1"
    shift
    goto :parse_args
)
if /I "%~1"=="--force" (
    set "FORCE_SETUP=1"
    shift
    goto :parse_args
)
if /I "%~1"=="--allow-cpu-torch" (
    set "CHECK_ARGS=!CHECK_ARGS! --allow-cpu-torch"
    set "UPDATE_ARGS=!UPDATE_ARGS! --allow-cpu-torch"
    shift
    goto :parse_args
)
echo [WARN] Ignoring unknown setup option: %~1
shift
goto :parse_args

:main
call :detect_py312

if not defined PYTHON_CMD (
    echo [INFO] Python 3.12 was not found. Trying winget install of Python 3.12...
    where winget >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] winget is not available and Python 3.12 is missing.
        echo [ERROR] Install Python 3.12 manually, then run setup_windows.bat again.
        set "SETUP_RESULT=failed; Python 3.12 is missing and winget is unavailable"
        set "EXIT_CODE=1"
        goto :finish
    )

    winget install --id Python.Python.3.12 --source winget --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo [ERROR] winget failed to install Python 3.12.
        echo [ERROR] Run manually: winget install --id Python.Python.3.12 --source winget
        set "SETUP_RESULT=failed; winget could not install Python 3.12"
        set "EXIT_CODE=1"
        goto :finish
    )

    call :detect_py312
)

if not defined PYTHON_CMD (
    where python >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] Python command was not found after installation attempt.
        set "SETUP_RESULT=failed; Python command was not found"
        set "EXIT_CODE=1"
        goto :finish
    )

    for /f "usebackq delims=" %%V in (`python -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"` ) do set "PY_VER=%%V"
    if not "%PY_VER%"=="3.12" (
        echo [ERROR] Python 3.12 is required for this repository.
        echo [ERROR] Found python version: %PY_VER%
        set "SETUP_RESULT=failed; Python 3.12 is required"
        set "EXIT_CODE=1"
        goto :finish
    )

    set "PYTHON_CMD=python"
)

for /f "usebackq delims=" %%V in (`%PYTHON_CMD% -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"` ) do set "PY_VER=%%V"
for /f "usebackq delims=" %%V in (`%PYTHON_CMD% -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}')"` ) do set "PY_VER_FULL=%%V"
echo [INFO] Python command: %PYTHON_CMD%
echo [INFO] Python version: %PY_VER_FULL%

if not "%PY_VER_FULL%"=="3.12.10" (
    echo [WARN] This repository is confirmed with Python 3.12.10.
    echo [WARN] Continuing with Python %PY_VER_FULL%.
)

call :ensure_ffmpeg
if errorlevel 1 (
    set "EXIT_CODE=1"
    goto :finish
)

if "%FORCE_SETUP%"=="0" if exist ".venv\Scripts\python.exe" (
    echo [INFO] Existing .venv found. Checking whether setup is already complete...
    %PYTHON_CMD% "%~dp0scripts\check_venv.py" %CHECK_ARGS%
    if not errorlevel 1 (
        if "!FFMPEG_SETUP_RESULT!"=="installed with winget" (
            set "SETUP_RESULT=existing .venv is ready; FFmpeg was installed"
        ) else (
            set "SETUP_RESULT=existing .venv is ready; no changes were made"
        )
        set "EXIT_CODE=0"
        goto :finish
    )
    echo [WARN] Existing .venv is missing or incomplete. Setup will rebuild it.
)

if "%FORCE_SETUP%"=="1" (
    echo [INFO] --force specified. Rebuilding .venv even if it already exists.
)

echo [INFO] Creating verified Python 3.12 environment
%PYTHON_CMD% "%~dp0scripts\update_venv.py" %UPDATE_ARGS%
if errorlevel 1 (
    echo [ERROR] venv setup failed
    set "SETUP_RESULT=failed; .venv setup did not complete"
    set "EXIT_CODE=1"
    goto :finish
)

set "SETUP_RESULT=.venv setup completed"
set "EXIT_CODE=0"
goto :finish

:finish
echo.
echo ========== Setup Summary ==========
if defined SETUP_RESULT (
    echo Result: %SETUP_RESULT%
) else (
    echo Result: setup did not complete
)
if defined PYTHON_CMD echo Python command: %PYTHON_CMD%
if defined PY_VER_FULL echo Python version: %PY_VER_FULL%
if defined FFMPEG_SETUP_RESULT echo FFmpeg: %FFMPEG_SETUP_RESULT%
if exist ".venv\Scripts\python.exe" (
    for /f "delims=" %%V in ('.venv\Scripts\python.exe -c "import sys; print(sys.version.split()[0])"') do echo .venv Python: %%V
) else (
    echo .venv Python: not installed
)
if exist ".cache\update_venv.log" echo Log file: "%~dp0.cache\update_venv.log"
echo ===================================
if "%PAUSE_ON_EXIT%"=="1" (
    echo.
    pause
)
exit /b %EXIT_CODE%

:detect_py312
where py >nul 2>&1
if not errorlevel 1 (
    py -3.12 -c "import sys" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_CMD=py -3.12"
        exit /b 0
    )
)

if not defined PYTHON_CMD if exist "!PY312_LOCAL!" (
    "!PY312_LOCAL!" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_CMD="!PY312_LOCAL!""
    )
)
if defined PYTHON_CMD exit /b 0

if not defined PYTHON_CMD if exist "!PY312_PROGRAMFILES!" (
    "!PY312_PROGRAMFILES!" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_CMD="!PY312_PROGRAMFILES!""
    )
)
if defined PYTHON_CMD exit /b 0

if not defined PYTHON_CMD if not "!PY312_PROGRAMFILES_X86!"=="\Python312\python.exe" if exist "!PY312_PROGRAMFILES_X86!" (
    "!PY312_PROGRAMFILES_X86!" -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_CMD="!PY312_PROGRAMFILES_X86!""
    )
)
if defined PYTHON_CMD exit /b 0

where python >nul 2>&1
if not errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON_CMD=python"
        exit /b 0
    )
)
exit /b 0

:ensure_ffmpeg
where ffmpeg >nul 2>&1
set "FFMPEG_FOUND=!errorlevel!"
where ffprobe >nul 2>&1
set "FFPROBE_FOUND=!errorlevel!"
if not "!FFMPEG_FOUND!!FFPROBE_FOUND!"=="00" (
    rem A newly installed winget package may not be on this terminal's inherited PATH yet.
    call :add_winget_ffmpeg_to_path
    where ffmpeg >nul 2>&1
    set "FFMPEG_FOUND=!errorlevel!"
    where ffprobe >nul 2>&1
    set "FFPROBE_FOUND=!errorlevel!"
)
if "!FFMPEG_FOUND!"=="0" if "!FFPROBE_FOUND!"=="0" (
    !PYTHON_CMD! -m core.ffmpeg_runtime
    if errorlevel 1 (
        echo [ERROR] Update FFmpeg and FFprobe to version 7 or newer, then run setup again.
        echo [INFO] For a winget installation: winget upgrade --id Gyan.FFmpeg --exact --source winget
        set "FFMPEG_SETUP_RESULT=failed; FFmpeg/FFprobe 7 or newer is required"
        set "SETUP_RESULT=failed; FFmpeg/FFprobe runtime check failed"
        exit /b 1
    )
    set "FFMPEG_SETUP_RESULT=version 7 or newer available on PATH"
    exit /b 0
)

echo [INFO] FFmpeg 7 or newer and its bundled FFprobe are required for frame extraction.
echo [INFO] FFmpeg or FFprobe was not found on PATH. Trying winget install of FFmpeg...
where winget >nul 2>&1
if errorlevel 1 (
    echo [ERROR] winget is not available and FFmpeg/FFprobe is missing.
    echo [ERROR] Install FFmpeg 7 or newer with FFprobe manually, then run setup_windows.bat again.
    set "FFMPEG_SETUP_RESULT=failed; FFmpeg/FFprobe is missing and winget is unavailable"
    set "SETUP_RESULT=failed; FFmpeg/FFprobe is missing"
    exit /b 1
)

winget install --id Gyan.FFmpeg --exact --source winget --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
    echo [ERROR] winget failed to install FFmpeg.
    echo [ERROR] Run manually: winget install --id Gyan.FFmpeg --exact --source winget
    set "FFMPEG_SETUP_RESULT=failed; winget could not install FFmpeg"
    set "SETUP_RESULT=failed; winget could not install FFmpeg"
    exit /b 1
)

call :add_winget_ffmpeg_to_path
where ffmpeg >nul 2>&1
set "FFMPEG_FOUND=!errorlevel!"
where ffprobe >nul 2>&1
set "FFPROBE_FOUND=!errorlevel!"
if not "!FFMPEG_FOUND!"=="0" (
    echo [ERROR] FFmpeg was installed, but ffmpeg.exe was not found on PATH.
    echo [ERROR] Open a new terminal, or add the FFmpeg bin folder to PATH manually.
    set "FFMPEG_SETUP_RESULT=failed; ffmpeg.exe was not found after install"
    set "SETUP_RESULT=failed; ffmpeg.exe was not found after install"
    exit /b 1
)
if not "!FFPROBE_FOUND!"=="0" (
    echo [ERROR] FFmpeg was installed, but ffprobe.exe was not found on PATH.
    echo [ERROR] Open a new terminal, or add the FFmpeg bin folder to PATH manually.
    set "FFMPEG_SETUP_RESULT=failed; ffprobe.exe was not found after install"
    set "SETUP_RESULT=failed; ffprobe.exe was not found after install"
    exit /b 1
)
%PYTHON_CMD% -m core.ffmpeg_runtime
if errorlevel 1 (
    echo [ERROR] The installed FFmpeg/FFprobe runtime did not pass the version 7+ check.
    echo [ERROR] Open a new terminal and check PATH for older FFmpeg copies, then run setup again.
    set "FFMPEG_SETUP_RESULT=failed; installed FFmpeg/FFprobe runtime check failed"
    set "SETUP_RESULT=failed; installed FFmpeg/FFprobe runtime check failed"
    exit /b 1
)
set "FFMPEG_SETUP_RESULT=installed with winget"
exit /b 0

:add_winget_ffmpeg_to_path
if exist "%LocalAppData%\Microsoft\WinGet\Links" (
    set "PATH=%LocalAppData%\Microsoft\WinGet\Links;%PATH%"
)
%PYTHON_CMD% -m core.ffmpeg_runtime >nul 2>&1
if not errorlevel 1 exit /b 0
set "FFMPEG_BIN="
if exist "%LocalAppData%\Microsoft\WinGet\Packages" (
    for /d %%P in ("%LocalAppData%\Microsoft\WinGet\Packages\Gyan.FFmpeg_*") do (
        for /f "delims=" %%F in ('where /R "%%~fP" ffmpeg.exe 2^>nul') do (
            if not defined FFMPEG_BIN if exist "%%~dpFffprobe.exe" (
                !PYTHON_CMD! -m core.ffmpeg_runtime --ffmpeg "%%~fF" --ffprobe "%%~dpFffprobe.exe" >nul 2>&1
                if not errorlevel 1 set "FFMPEG_BIN=%%~dpF"
            )
        )
    )
)
if defined FFMPEG_BIN set "PATH=!FFMPEG_BIN!;%PATH%"
exit /b 0
