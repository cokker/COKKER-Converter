import os, sys, subprocess, shutil, ctypes, threading
from pathlib import Path
from contextlib import contextmanager

REPO='https://github.com/cokker/COKKER-Converter'
URLS={'ffmpeg':'https://ffmpeg.org/download.html','soffice':'https://www.libreoffice.org/download/download-libreoffice/','ebook-convert':'https://calibre-ebook.com/download','7z':'https://www.7-zip.org/'}

def executable(name):
    base=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent
    suffix='.exe' if os.name=='nt' else ''
    candidates=[base/'components'/f'{name}{suffix}']
    if os.name=='nt':
        pf=Path(os.environ.get('ProgramFiles','C:/Program Files'))
        local=Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData/Local'))
        candidates += [local/'Microsoft/WinGet/Links'/f'{name}.exe']
        candidates += [pf/'LibreOffice/program/soffice.exe'] if name=='soffice' else []
        candidates += [Path(os.environ.get('ProgramFiles(x86)','C:/Program Files (x86)'))/'LibreOffice/program/soffice.exe'] if name=='soffice' else []
        candidates += [pf/'Calibre2/ebook-convert.exe'] if name=='ebook-convert' else []
        candidates += [pf/'7-Zip/7z.exe'] if name=='7z' else []
    return next((str(p) for p in candidates if p.is_file()),shutil.which(name))

def startup(enabled,tray):
    if os.name!='nt': raise RuntimeError('Автозапуск доступен в Windows.')
    import winreg
    cmd=[sys.executable]
    if not getattr(sys,'frozen',False): cmd += [str(Path(__file__).resolve().parent.parent/'main.py')]
    if tray: cmd+=['--tray']
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
        if enabled: winreg.SetValueEx(key,'COKKERConverter',0,winreg.REG_SZ,subprocess.list2cmdline(cmd))
        else:
            try: winreg.DeleteValue(key,'COKKERConverter')
            except FileNotFoundError: pass

@contextmanager
def keep_awake(enabled=True):
    if enabled and os.name=='nt': ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    try: yield
    finally:
        if enabled and os.name=='nt': ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)

class Cancelled(Exception): pass

class ProcessRunner:
    def __init__(self,cancel=None): self.cancel=cancel or threading.Event()
    def run(self,args,progress=None,duration=0,cwd=None):
        import tempfile, signal
        if self.cancel.is_set(): raise Cancelled('Отменено')
        flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
        with tempfile.TemporaryFile(mode='w+b') as err:
            p=subprocess.Popen([str(a) for a in args],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=err,
                               cwd=cwd,creationflags=flags,start_new_session=os.name!='nt',text=True,encoding='utf-8',errors='replace')
            def monitor():
                while p.poll() is None:
                    if self.cancel.wait(.1):
                        if p.poll() is not None: break
                        if os.name=='nt': subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True,creationflags=flags)
                        else:
                            try: os.killpg(p.pid,signal.SIGKILL)
                            except ProcessLookupError: pass
                        break
            watcher=threading.Thread(target=monitor,daemon=True); watcher.start()
            output=[]
            for line in p.stdout:
                if progress and line.startswith('out_time_us=') and duration:
                    try: progress(min(.99,float(line.split('=',1)[1])/1e6/duration))
                    except ValueError: pass
                elif sum(map(len,output))<2_000_000: output.append(line)
            p.wait(); watcher.join(timeout=.2)
            if self.cancel.is_set(): raise Cancelled('Отменено')
            if p.returncode:
                err.seek(0); detail=err.read().decode('utf-8','replace')[-5000:]
                raise RuntimeError(detail or f'Компонент завершился с кодом {p.returncode}.')
            return ''.join(output)
