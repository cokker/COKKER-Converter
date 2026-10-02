import json, os, sys, sqlite3, threading, tempfile
from pathlib import Path
from dataclasses import asdict, fields
from .models import Options, Job
from .registry import REGISTRY

def root_dir():
    base = Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent
    if (base/'portable.flag').exists(): return base/'data'
    return Path(os.environ.get('LOCALAPPDATA',Path.home()/'.local/share'))/'COKKER Converter'

def atomic_json(path, data):
    path = Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name, suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False,indent=2); f.flush(); os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)

class Store:
    def __init__(self, root=None):
        self.root = Path(root) if root else root_dir(); self.root.mkdir(parents=True,exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root/'state.db',check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, data TEXT NOT NULL)')
        self.db.commit()
    def get(self,key,default=None):
        with self.lock:
            row=self.db.execute('SELECT data FROM settings WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else default
    def set(self,key,value):
        with self.lock:
            self.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(key,json.dumps(value,ensure_ascii=False))); self.db.commit()
    def save_job(self,job):
        with self.lock:
            self.db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?)',(job.id,json.dumps(job.serialize(),ensure_ascii=False))); self.db.commit()
    def jobs(self):
        with self.lock: rows=self.db.execute('SELECT data FROM jobs ORDER BY rowid').fetchall()
        return [Job(**json.loads(r[0])) for r in rows]
    def delete_job(self,id):
        with self.lock: self.db.execute('DELETE FROM jobs WHERE id=?',(id,)); self.db.commit()

class Presets:
    def __init__(self,store): self.store=store
    def all(self): return self.store.get('presets',[])
    def save(self,items):
        for p in items: self.validate(p)
        self.store.set('presets',items)
    @staticmethod
    def validate(p):
        if not isinstance(p,dict) or type(p.get('schemaVersion')) is not int: raise ValueError('Некорректный JSON пресета.')
        if p['schemaVersion'] != 1: raise ValueError('Этот пресет создан в другой версии. Поддерживается schemaVersion=1.')
        if p.get('operation') not in REGISTRY: raise ValueError('Неизвестная операция.')
        if not isinstance(p.get('presetName'),str) or not 1 <= len(p['presetName']) <= 120: raise ValueError('Некорректное имя.')
        if not isinstance(p.get('parameters'),dict): raise ValueError('Некорректные параметры.')
        allowed={f.name for f in fields(Options)}-{'extra_file'}
        if set(p['parameters'])-allowed: raise ValueError('Недопустимые или приватные параметры.')
        o=Options(**p['parameters']); o.validate()
        if o.format not in REGISTRY[p['operation']].formats: raise ValueError('Недопустимый формат.')
    def import_file(self,path):
        if Path(path).stat().st_size > 1024*1024: raise ValueError('Файл пресетов слишком большой.')
        data=json.loads(Path(path).read_text(encoding='utf-8'))
        items=data if isinstance(data,list) else [data]
        if len(items)>500: raise ValueError('Слишком много пресетов.')
        for p in items: self.validate(p)
        self.save(self.all()+items)
    def export_file(self,path,items):
        for p in items: self.validate(p)
        atomic_json(path,items)
