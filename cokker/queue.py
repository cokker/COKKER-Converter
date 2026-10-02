import threading, time, logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject, Signal
from .engine import Engine
from .platform_services import Cancelled, keep_awake

class Queue(QObject):
    changed=Signal()
    completed=Signal(str)
    def __init__(self,store):
        super().__init__(); self.store=store; self.lock=threading.RLock()
        self.jobs=store.jobs(); self.pool=ThreadPoolExecutor(max_workers=4,thread_name_prefix='conversion')
        self.active={}; self.paused=False; self.stopping=False
        for j in self.jobs:
            if j.status in ('running','waiting'): j.status='interrupted'; j.progress=0; store.save_job(j)
    def add(self,jobs):
        with self.lock:
            for j in jobs:
                j.created=datetime.now(timezone.utc).isoformat(); self.jobs.append(j); self.store.save_job(j)
        self.changed.emit(); self.pump()
    def pump(self):
        with self.lock:
            if self.paused or self.stopping: return
            limit=min(4,max(1,self.store.get('concurrency',1)))
            for j in self.jobs:
                if len(self.active)>=limit: break
                if j.status=='waiting':
                    event=threading.Event(); self.active[j.id]=event; j.status='running'; self.store.save_job(j)
                    self.pool.submit(self.work,j,event)
    def work(self,j,event):
        last=0
        def progress(value):
            nonlocal last
            j.progress=value
            if time.monotonic()-last>.15: self.changed.emit(); last=time.monotonic()
        try:
            with keep_awake(self.store.get('sleep_block',True)):
                j.output,j.before,j.after,j.elapsed=Engine(event,progress).convert(j)
            j.status='done'; j.progress=1; j.error=''
        except Cancelled: j.status='cancelled'; j.error='Отменено пользователем'
        except Exception as e:
            logging.exception('Conversion failed'); j.status='failed'; j.error=str(e)
        finally:
            with self.lock:
                self.store.save_job(j); self.active.pop(j.id,None)
            self.changed.emit(); self.completed.emit(j.id); self.pump()
    def cancel(self,ids):
        with self.lock:
            for j in self.jobs:
                if j.id not in ids: continue
                if j.id in self.active: self.active[j.id].set()
                elif j.status in ('waiting','interrupted'): j.status='cancelled'; self.store.save_job(j)
        self.changed.emit()
    def retry(self,ids):
        with self.lock:
            for j in self.jobs:
                if j.id in ids and j.id not in self.active:
                    j.status='waiting'; j.progress=0; j.error=''; self.store.save_job(j)
        self.changed.emit(); self.pump()
    def remove(self,ids):
        with self.lock:
            for j in list(self.jobs):
                if j.id in ids and j.id not in self.active: self.jobs.remove(j); self.store.delete_job(j.id)
        self.changed.emit()
    def shutdown(self):
        self.stopping=True
        with self.lock:
            for event in self.active.values(): event.set()
        self.pool.shutdown(wait=True,cancel_futures=True)
