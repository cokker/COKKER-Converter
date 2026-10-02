# Сборка Windows x64

В репозитории workflow `Windows x64` на `windows-2022` запускает `pytest`, собирает PyInstaller `onedir`, устанавливает через Chocolatey FFmpeg и Inno Setup, создаёт Portable ZIP и Setup EXE. Тег вида `v0.9.3` запускает публикацию GitHub prerelease лишь после успешной проверки и сборки. Если workflow завершился с ошибкой, не считайте файлы выпущенными. Проверьте совпадение номера версии в `cokker/__init__.py` и `packaging/setup.iss`.

Локально: Python 3.12 x64, FFmpeg/ffprobe в PATH, Inno Setup 6. Выполните из корня:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt pytest pyinstaller
$env:QT_QPA_PLATFORM='offscreen'
.venv\Scripts\python.exe -m pytest -q
Remove-Item Env:QT_QPA_PLATFORM
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --onedir --name "COKKER Converter" --icon "assets/logo.ico" --add-data "assets;assets" --collect-all pillow_heif --collect-all pypdfium2 main.py
New-Item -ItemType Directory -Force "dist/COKKER Converter/components"
Copy-Item (Get-Command ffmpeg.exe).Source "dist/COKKER Converter/components/ffmpeg.exe"
Copy-Item (Get-Command ffprobe.exe).Source "dist/COKKER Converter/components/ffprobe.exe"
New-Item -ItemType File "dist/COKKER Converter/portable.flag"
Compress-Archive -Path "dist/COKKER Converter" -DestinationPath "dist/COKKER-Converter-Portable-x64.zip" -Force
Remove-Item "dist/COKKER Converter/portable.flag"
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" "packaging/setup.iss"
```

Лицензии компонентов FFmpeg из Chocolatey нужно сохранить рядом с дистрибутивом, если конкретный пакет их предоставляет. Для публичного распространения проверьте соблюдение лицензии выбранного бинарника FFmpeg и предоставьте исходники/notice согласно её условиям. Не заявляйте о Windows-проверке, пока CI не прошёл.
