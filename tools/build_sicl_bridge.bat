@echo off
setlocal
set "VSDIR=C:\Program Files\Microsoft Visual Studio\2022\Community"
set "VCDIR=%VSDIR%\VC\Auxiliary\Build"
set "SICL=C:\Program Files\Keysight\IO Libraries Suite"

call "%VCDIR%\vcvars64.bat" >nul
if errorlevel 1 (
  echo Could not initialize Visual Studio x64 environment.
  exit /b 1
)

cl /nologo /O2 /W3 /D_CRT_SECURE_NO_WARNINGS ^
  /I"%SICL%\include" ^
  "%~dp0sicl_bridge.c" ^
  /link /LIBPATH:"%SICL%\lib_x64" sicl32.lib ^
  /OUT:"%~dp0sicl_bridge.exe"
if errorlevel 1 exit /b 1

echo Built %~dp0sicl_bridge.exe
