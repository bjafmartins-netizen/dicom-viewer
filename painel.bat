@echo off
REM Abre o painel do miniPACS (janela com botoes). Dois cliques neste arquivo.
REM Procura um Python com Tkinter; defina MINIPACS_PYTHON para apontar outro.
setlocal

set "PAINEL=%~dp0scripts\painel.py"

if not "%MINIPACS_PYTHON%"=="" (
  if exist "%MINIPACS_PYTHON%" set "PY=%MINIPACS_PYTHON%"
)
if "%PY%"=="" if exist "E:\winPY\python\pythonw.exe" set "PY=E:\winPY\python\pythonw.exe"
if "%PY%"=="" for %%P in (pythonw.exe) do if not "%%~$PATH:P"=="" set "PY=%%~$PATH:P"
if "%PY%"=="" for %%P in (python.exe) do if not "%%~$PATH:P"=="" set "PY=%%~$PATH:P"

if "%PY%"=="" (
  echo ERRO: nao encontrei um Python para abrir o painel.
  echo Defina MINIPACS_PYTHON com o caminho do pythonw.exe, por exemplo:
  echo   set MINIPACS_PYTHON=E:\winPY\python\pythonw.exe
  pause
  exit /b 1
)

REM pythonw nao abre console; com python.exe, o start "" evita travar o terminal.
start "" "%PY%" "%PAINEL%"
endlocal
