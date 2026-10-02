import hashlib
import io
import tempfile
import zipfile
from pathlib import Path
import pytest
from cokker.updater import Release,select_release,download,prepare_portable,apply_portable
from cokker import __version__

def test_installer_version_matches_app():
    assert f'#define AppVersion "{__version__}"' in (Path(__file__).parents[1]/'packaging'/'setup.iss').read_text(encoding='utf-8')

def test_prerelease_updates_require_both_binaries():
    assets=[{'name':name,'state':'uploaded'} for name in ('COKKER-Converter-Portable-x64.zip','COKKER-Converter-Setup-x64.exe')]
    releases=[{'tag_name':'v0.9.4','prerelease':True,'assets':assets[:1]},
              {'tag_name':'v0.9.3','prerelease':True,'assets':assets,'html_url':'https://github.com/cokker/COKKER-Converter/releases/tag/v0.9.3'},
              {'tag_name':'v0.9.1','prerelease':True,'assets':assets}]
    chosen=select_release(releases,'0.9.2')
    assert chosen and chosen.version=='v0.9.3'
    assert select_release(releases,'0.9.3') is None

def test_update_download_verifies_bytes(monkeypatch):
    payload=b'COKKER verified update';name='COKKER-Converter-Portable-x64.zip'
    asset={'name':name,'browser_download_url':'https://github.com/cokker/COKKER-Converter/releases/download/v0.9.3/'+name,
           'size':len(payload),'digest':'sha256:'+hashlib.sha256(payload).hexdigest()}
    release=Release('v0.9.3','https://github.com/cokker/COKKER-Converter/releases/tag/v0.9.3',{name:asset})
    monkeypatch.setattr('cokker.updater.urllib.request.urlopen',lambda *args,**kwargs:io.BytesIO(payload))
    with tempfile.TemporaryDirectory() as folder:
        result=download(release,'portable',folder)
        assert result.read_bytes()==payload
        result.write_bytes(b'broken')
        monkeypatch.setattr('cokker.updater.urllib.request.urlopen',lambda *args,**kwargs:io.BytesIO(b'wrong'))
        with pytest.raises(RuntimeError):download(release,'portable',folder)
        assert not (Path(folder)/(name+'.part')).exists()

def test_portable_archive_rejects_escape_and_has_expected_layout():
    with tempfile.TemporaryDirectory() as folder:
        folder=Path(folder);archive=folder/'good.zip'
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('COKKER Converter/COKKER Converter.exe',b'binary')
            z.writestr('COKKER Converter/portable.flag',b'')
            z.writestr('COKKER Converter/_internal/module.dll',b'dll')
        base=prepare_portable(archive,folder/'stage')
        assert (base/'COKKER Converter.exe').read_bytes()==b'binary'
        with zipfile.ZipFile(archive,'w') as z:z.writestr('COKKER Converter/../../escape.txt',b'bad')
        with pytest.raises(ValueError):prepare_portable(archive,folder/'stage2')

def test_portable_replacement_preserves_user_data(monkeypatch):
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);source=root/'new';target=root/'installed'
        for path in (source,target):
            (path/'_internal').mkdir(parents=True);(path/'portable.flag').touch()
        (source/'COKKER Converter.exe').write_bytes(b'new')
        (source/'_internal'/'app.dll').write_bytes(b'new dll')
        (target/'COKKER Converter.exe').write_bytes(b'old')
        (target/'data').mkdir();(target/'data'/'presets.json').write_text('keep me')
        calls=[];monkeypatch.setattr('cokker.updater.subprocess.Popen',lambda args,**kwargs:calls.append(args))
        apply_portable(source,target,0)
        assert (target/'COKKER Converter.exe').read_bytes()==b'new'
        assert (target/'_internal'/'app.dll').read_bytes()==b'new dll'
        assert (target/'data'/'presets.json').read_text()=='keep me'
        assert Path(calls[0][0]).samefile(target/'COKKER Converter.exe')

def test_portable_replacement_rolls_back_on_launch_failure(monkeypatch):
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);source=root/'new';target=root/'installed'
        source.mkdir();target.mkdir()
        for path in (source,target):(path/'portable.flag').touch()
        (source/'COKKER Converter.exe').write_bytes(b'new')
        (target/'COKKER Converter.exe').write_bytes(b'old')
        (target/'data').mkdir();(target/'data'/'settings.db').write_bytes(b'original')
        monkeypatch.setattr('cokker.updater.subprocess.Popen',lambda *a,**kw:(_ for _ in ()).throw(OSError('blocked')))
        with pytest.raises(OSError):apply_portable(source,target,0)
        assert (target/'COKKER Converter.exe').read_bytes()==b'old'
        assert (target/'data'/'settings.db').read_bytes()==b'original'
