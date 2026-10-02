"""Verified GitHub release downloads and safe Portable replacement."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

API = 'https://api.github.com/repos/cokker/COKKER-Converter/releases?per_page=30'
DOWNLOAD_PREFIX = 'https://github.com/cokker/COKKER-Converter/releases/download/'
ASSETS = {'portable': 'COKKER-Converter-Portable-x64.zip', 'setup': 'COKKER-Converter-Setup-x64.exe'}

@dataclass(frozen=True)
class Release:
    version: str
    url: str
    assets: dict

def version_key(value):
    match=re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:[-.]([0-9A-Za-z.-]+))?',value)
    if not match: return None
    return tuple(map(int,match.group(1,2,3)))+(0 if match.group(4) else 1,)

def select_release(data,current):
    current_key=version_key(current)
    if current_key is None: raise ValueError('Неизвестная версия установленной программы.')
    eligible=[]
    for item in data:
        key=version_key(item.get('tag_name',''))
        if not key or item.get('draft') or key<=current_key:continue
        assets={a['name']:a for a in item.get('assets',[]) if a.get('state')=='uploaded'}
        if all(n in assets for n in ASSETS.values()):eligible.append((key,item,assets))
    if not eligible:return None
    _,item,assets=max(eligible,key=lambda value:value[0])
    return Release(item['tag_name'],item['html_url'],assets)

def check_release(current):
    request=urllib.request.Request(API,headers={'User-Agent':'COKKER-Converter','Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(request,timeout=15) as response:data=json.load(response)
    if not isinstance(data,list):raise RuntimeError('GitHub не вернул список выпусков.')
    return select_release(data,current)

def download(release,kind,target_dir,progress=lambda value:None,cancel=None):
    asset=release.assets[ASSETS[kind]]
    url=asset['browser_download_url']
    if not url.startswith(DOWNLOAD_PREFIX+release.version+'/'):raise ValueError('Некорректный адрес файла обновления.')
    digest=asset.get('digest','')
    if not re.fullmatch(r'sha256:[0-9a-fA-F]{64}',digest):raise ValueError('GitHub не предоставил контрольную сумму файла.')
    expected=int(asset['size'])
    if expected<=0:raise ValueError('Файл обновления пуст.')
    folder=Path(target_dir);folder.mkdir(parents=True,exist_ok=True)
    target=folder/ASSETS[kind];partial=folder/(target.name+'.part')
    if target.is_file() and target.stat().st_size==expected and _hash(target)==digest[7:].lower():
        progress(100);return target
    try:
        request=urllib.request.Request(url,headers={'User-Agent':'COKKER-Converter'})
        with urllib.request.urlopen(request,timeout=30) as response,partial.open('wb') as output:
            checksum=hashlib.sha256();received=0
            while True:
                if cancel and cancel.is_set():raise InterruptedError('Загрузка отменена.')
                chunk=response.read(256*1024)
                if not chunk:break
                output.write(chunk);checksum.update(chunk);received+=len(chunk)
                progress(min(99,int(received*100/expected)))
            output.flush();os.fsync(output.fileno())
        if received!=expected or checksum.hexdigest()!=digest[7:].lower():
            raise RuntimeError('Размер или контрольная сумма обновления не совпали. Файл удалён.')
        os.replace(partial,target);progress(100);return target
    finally:
        partial.unlink(missing_ok=True)

def _hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def prepare_portable(archive,staging):
    staging=Path(staging);staging.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        members=source.infolist()
        if not members or len(members)>20000:raise ValueError('Неверный архив обновления.')
        for entry in members:
            name=PurePosixPath(entry.filename)
            if name.is_absolute() or '..' in name.parts or name.parts[0]!='COKKER Converter' or '\\' in entry.filename:
                raise ValueError('Недопустимый путь в архиве обновления.')
            if len(name.parts)>1 and name.parts[1]=='data':raise ValueError('Архив обновления не должен содержать пользовательские данные.')
            if (entry.external_attr>>16)&0o170000==0o120000:raise ValueError('Архив содержит ссылку.')
        source.extractall(staging)
    base=staging/'COKKER Converter'
    if not (base/'COKKER Converter.exe').is_file() or not (base/'portable.flag').is_file() or not (base/'_internal').is_dir():
        raise ValueError('В архиве отсутствует Portable-приложение.')
    return base

def apply_portable(source,destination,old_pid):
    """Called by the *new* EXE from its staging directory after the old one exits."""
    source=Path(source).resolve();destination=Path(destination).resolve()
    if source==destination or destination in source.parents or not (source/'portable.flag').is_file() or not (destination/'portable.flag').is_file():
        raise ValueError('Неверные папки Portable-обновления.')
    suffix=uuid.uuid4().hex[:8]
    next_dir=destination.with_name(destination.name+'.next-'+suffix)
    backup=destination.with_name(destination.name+'.backup-'+suffix)
    shutil.copytree(source,next_dir)
    try:
        if os.name=='nt':
            import ctypes
            handle=ctypes.windll.kernel32.OpenProcess(0x00100000,False,int(old_pid))
            if handle:
                try:
                    result=ctypes.windll.kernel32.WaitForSingleObject(handle,60000)
                    if result!=0:raise TimeoutError('Предыдущая версия не закрылась за 60 секунд.')
                finally:ctypes.windll.kernel32.CloseHandle(handle)
        for attempt in range(6):
            try:os.replace(destination,backup);break
            except OSError:
                if attempt==5:raise
                time.sleep(1)
        os.replace(next_dir,destination)
        if (backup/'data').exists():os.replace(backup/'data',destination/'data')
        subprocess.Popen([str(destination/'COKKER Converter.exe')],cwd=destination,close_fds=True)
    except Exception:
        if backup.exists():
            if destination.exists():
                if (destination/'data').exists() and not (backup/'data').exists():
                    os.replace(destination/'data',backup/'data')
                shutil.rmtree(destination)
            os.replace(backup,destination)
        raise
    finally:
        if next_dir.exists():shutil.rmtree(next_dir,ignore_errors=True)
