@echo off
REM ---------------------------------------------------------------------
REM make.cmd -- Windows shim so that "make <target>" works without GNU make.
REM Keep this file pure ASCII: cmd.exe reads it in the OEM code page.
REM ---------------------------------------------------------------------
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0make.ps1" %*
