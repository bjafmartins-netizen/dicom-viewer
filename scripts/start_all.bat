@echo off
REM Sobe o miniPACS completo no Windows: Orthanc + OHIF.
REM Cada serviço abre em sua própria janela; feche a janela para encerrar.
setlocal

set "RAIZ=%~dp0.."
set "PACS_DIR=%RAIZ%\pacs"
set "OHIF_DIST=%RAIZ%\viewer-ohif\dist"
if "%ORTHANC_PORT%"=="" set "ORTHANC_PORT=8042"
if "%OHIF_PORT%"=="" set "OHIF_PORT=3000"

if not exist "%PACS_DIR%\Orthanc.exe" (
  echo ERRO: pacs\Orthanc.exe nao encontrado.
  echo Baixe a versao portatil do Orthanc e extraia em pacs\ ^(veja pacs\README.md^).
  pause
  exit /b 1
)

echo Subindo Orthanc na porta %ORTHANC_PORT% ...
start "Orthanc (miniPACS)" cmd /k "cd /d ""%PACS_DIR%"" && Orthanc.exe orthanc.json"

REM Da um tempo para o servidor iniciar antes de abrir o navegador
timeout /t 3 /nobreak >nul

if exist "%OHIF_DIST%\index.html" (
  echo Servindo OHIF na porta %OHIF_PORT% ...
  start "OHIF Viewer" cmd /k "python -m http.server %OHIF_PORT% --directory ""%OHIF_DIST%"""
  timeout /t 2 /nobreak >nul
  start "" "http://localhost:%OHIF_PORT%"
) else (
  echo AVISO: build do OHIF nao encontrado em viewer-ohif\dist ^(veja viewer-ohif\README.md^).
  echo        Abrindo a interface propria do Orthanc.
  start "" "http://localhost:%ORTHANC_PORT%"
)

echo.
echo Orthanc Explorer: http://localhost:%ORTHANC_PORT%
echo Importar exames:  python scripts\import_folder.py --input data\phantom
echo.
echo Feche as janelas abertas para encerrar os servicos.
endlocal
