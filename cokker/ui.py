import json, os, sys, uuid, time
from pathlib import Path
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QUrl, QMimeData
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QDesktopServices, QPixmap, QIcon, QPainter, QColor
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QFormLayout,QLabel,QPushButton,QListWidget,QListWidgetItem,QStackedWidget,QScrollArea,QFrame,QComboBox,QSpinBox,QDoubleSpinBox,QLineEdit,QCheckBox,QFileDialog,QMessageBox,QInputDialog,QProgressBar,QSystemTrayIcon,QMenu,QDialog,QDialogButtonBox,QSplitter)
from . import __version__
from .models import Options,Job
from .registry import OPERATIONS,REGISTRY,category
from .storage import Store,Presets
from .queue import Queue
from .engine import Engine
from .platform_services import executable,URLS,REPO,startup,latest_release
from .style import stylesheet
from .widgets import FileList,Results,CropCanvas,Section

class Async(QObject):
    result=Signal(object,object)
    def __init__(self):
        super().__init__(); self.pool=ThreadPoolExecutor(max_workers=2); self.result.connect(self.deliver)
    def deliver(self,callback,value): callback(value)
    def run(self,fn,callback):
        def work():
            try: value=fn()
            except Exception as e: value=e
            self.result.emit(callback,value)
        self.pool.submit(work)

def label(text,kind=None):
    w=QLabel(text); w.setWordWrap(True)
    if kind: w.setObjectName(kind)
    return w

def button(text,fn,primary=False):
    b=QPushButton(text); b.clicked.connect(lambda checked=False:fn())
    if primary: b.setObjectName('primary')
    return b

def spin(lo,hi,value=0,decimal=False):
    w=QDoubleSpinBox() if decimal else QSpinBox(); w.setRange(lo,hi); w.setValue(value); w.setFocusPolicy(Qt.FocusPolicy.StrongFocus); return w

def combo(items):
    w=QComboBox(); w.addItems(items); w.setFocusPolicy(Qt.FocusPolicy.StrongFocus); return w

def card():
    w=QFrame(); w.setObjectName('card'); l=QVBoxLayout(w); l.setSpacing(12); return w,l

STATUS={'waiting':'Ожидает','running':'Обработка','interrupted':'Прервано — восстановить?','done':'Готово','cancelled':'Отменено','failed':'Ошибка'}

def size(n):
    for unit in ('Б','КБ','МБ','ГБ','ТБ'):
        if n<1024: return f'{n:.1f} {unit}'
        n/=1024
    return f'{n:.1f} ПБ'

class Window(QMainWindow):
    def __init__(self,store=None):
        super().__init__(); self.store=store or Store(); self.presets=Presets(self.store); self.queue=Queue(self.store); self.async_=Async()
        self.setWindowTitle('COKKER Converter'); self.resize(1180,820); self.setMinimumSize(840,600); self.setAcceptDrops(True)
        self.exiting=False; self.current='Главная'; self.queue_rows={}; self.controls={}; self.notice_timer=QTimer(self)
        self.build_icon(); self.setWindowIcon(self.icon); self.build(); self.build_tray(); self.apply_theme()
        self.queue.changed.connect(self.refresh_queue); self.queue.completed.connect(self.completed)
        self.tick=QTimer(self); self.tick.timeout.connect(self.refresh_queue); self.tick.start(700)
        self.save_timer=QTimer(self); self.save_timer.setSingleShot(True); self.save_timer.timeout.connect(self.save_window)
        for keys,fn in [('Ctrl+O',self.choose_files),('Ctrl+Shift+O',self.choose_folder),('Ctrl+V',self.paste),('Ctrl+Return',self.enqueue),('Ctrl+,',lambda:self.navigate('Настройки')),('Ctrl+F',lambda:self.search.setFocus())]:
            shortcut=QShortcut(QKeySequence(keys),self); shortcut.activated.connect(fn)
        self.navigate('Главная'); QApplication.instance().installEventFilter(self)
        geometry=self.store.get('geometry')
        if geometry: self.resize(max(840,geometry[0]),max(600,geometry[1]))
        if any(j.status=='interrupted' for j in self.queue.jobs): QTimer.singleShot(400,self.recovery)
    def build_icon(self):
        pix=QPixmap(64,64); pix.fill(Qt.GlobalColor.transparent); p=QPainter(pix); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor('#ff9c56')); p.setPen(Qt.PenStyle.NoPen); p.drawRoundedRect(3,3,58,58,16,16)
        p.setPen(QColor('#171a21')); font=p.font(); font.setPixelSize(40); font.setBold(True); p.setFont(font); p.drawText(pix.rect(),Qt.AlignmentFlag.AlignCenter,'C'); p.end(); self.icon=QIcon(pix)
    def build(self):
        central=QWidget(); self.setCentralWidget(central); root=QHBoxLayout(central); root.setContentsMargins(18,18,18,18); root.setSpacing(22)
        side=QWidget(); side.setFixedWidth(210); sl=QVBoxLayout(side); sl.setContentsMargins(0,0,0,0)
        sl.addWidget(label('COKKER\nConverter','brand'))
        self.nav=QListWidget(); self.nav.setObjectName('nav')
        self.nav.addItems(['Главная','Избранное','Очередь','История','Видео','Аудио','Изображения','Документы','PDF','Архивы','Электронные книги','VRChat','Настройки','О программе'])
        self.nav.currentTextChanged.connect(self.navigate); sl.addWidget(self.nav); sl.addWidget(label('Локально. Быстро. Твои файлы.','subtitle')); root.addWidget(side)
        main=QWidget(); ml=QVBoxLayout(main); ml.setContentsMargins(0,0,0,0); ml.setSpacing(16)
        top=QHBoxLayout(); self.heading=label('Начнём с файла','title'); top.addWidget(self.heading,1)
        self.search=QLineEdit(); self.search.setPlaceholderText('Найти инструмент   Ctrl+F'); self.search.setMaximumWidth(300); self.search.textChanged.connect(self.filter_tools); top.addWidget(self.search); ml.addLayout(top)
        self.notice=label(''); self.notice.setStyleSheet('color:#ff9c56;padding:8px;'); self.notice.hide(); ml.addWidget(self.notice)
        self.pages=QStackedWidget(); ml.addWidget(self.pages,1); root.addWidget(main,1)
        self.home,self.home_layout=self.page(); self.tools_widget=QWidget(); self.tools_grid=QGridLayout(self.tools_widget); self.tools_grid.setContentsMargins(0,0,0,0)
        self.home_layout.addWidget(label('Перетащи файлы, выбери действие — остальное сделаем здесь.','subtitle'))
        drop,dl=card(); dl.addWidget(label('Добавь видео, музыку, изображения или документы','title'))
        dl.addWidget(label('Перетаскивание файлов и папок • Ctrl+V из буфера обмена','subtitle'))
        actions=QHBoxLayout(); actions.addWidget(button('Выбрать файлы',self.choose_files,True)); actions.addWidget(button('Добавить папку',self.choose_folder)); actions.addStretch(); dl.addLayout(actions); self.home_layout.addWidget(drop)
        self.home_layout.addWidget(self.tools_widget); self.home_layout.addStretch()
        self.editor,self.editor_layout=self.page(); self.build_editor()
        self.queue_page,self.ql=self.page(); self.queue_list=Results(); self.queue_list.setMinimumHeight(350); self.ql.addWidget(self.queue_list,1)
        self.progress=QProgressBar(); self.ql.addWidget(self.progress)
        row=QHBoxLayout()
        for text,fn in [('Открыть',self.open_result),('Папка',self.open_folder),('Копировать файлы',self.copy_results),('Копировать изображение',self.copy_image),('Повторить',self.retry),('Отменить',self.cancel),('Убрать',self.remove)]: row.addWidget(button(text,fn))
        self.ql.addLayout(row); self.ql.addWidget(button('Подробности ошибки',self.error_details)); self.queue_list.itemDoubleClicked.connect(lambda _:self.open_result())
        self.extra,self.extra_layout=self.page()
        self.rebuild_tools()
    def page(self):
        content=QWidget(); layout=QVBoxLayout(content); layout.setContentsMargins(4,4,12,12); layout.setSpacing(16)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(content); self.pages.addWidget(scroll); return scroll,layout
    def build_editor(self):
        self.editor_layout.addWidget(label('1  Исходные файлы','subtitle'))
        self.files=FileList(); self.files.filesDropped.connect(self.add_paths); self.files.itemDoubleClicked.connect(lambda _:self.inspect()); self.editor_layout.addWidget(self.files)
        row=QHBoxLayout()
        for text,fn in [('Добавить',self.choose_files),('Папка',self.choose_folder),('Удалить выбранные',self.remove_inputs),('Информация',self.inspect),('Preview / Crop',self.preview)]: row.addWidget(button(text,fn))
        self.editor_layout.addLayout(row)
        basic,bl=card(); form=QFormLayout(); form.setSpacing(12); self.operation=QComboBox()
        for op in OPERATIONS: self.operation.addItem(op.label,op.id)
        self.operation.currentIndexChanged.connect(self.operation_changed)
        form.addRow('Действие',self.operation); self.format=QComboBox(); form.addRow('Формат',self.format)
        self.quality=combo(['Сбалансированное','Высокое качество','Максимальное сжатие']); form.addRow('Качество',self.quality)
        self.resolution=combo(['Оригинальное','3840 × 2160','2560 × 1440','1920 × 1080','1280 × 720','1080 × 1920','1080 × 1080','512 × 512'])
        form.addRow('Разрешение',self.resolution); bl.addLayout(form); self.editor_layout.addWidget(basic)
        advanced=QWidget(); af=QFormLayout(advanced); af.setSpacing(10)
        def add(key,text,w): self.controls[key]=w; af.addRow(text,w)
        add('width','Ширина (0 = авто)',spin(0,16384)); add('height','Высота (0 = авто)',spin(0,16384))
        add('scale_mode','Размер: вписать / заполнить / растянуть',combo(['fit','fill','stretch']))
        add('no_upscale','Не увеличивать исходник',QCheckBox()); self.controls['no_upscale'].setChecked(True)
        add('start','Начало, секунд',spin(0,999999,0,True)); add('end','Конец, секунд (0 = до конца)',spin(0,999999,0,True))
        add('crop','Crop: X,Y,ширина,высота',QLineEdit()); add('rotate','Поворот по часовой стрелке',combo(['0','90','180','270']))
        add('flip','Отражение',combo(['none','horizontal','vertical'])); add('fps','FPS (0 = исходный)',spin(0,240,0,True)); add('speed','Скорость, ×',spin(.1,16,1,True))
        add('codec','Видеокодек',combo(['auto','libx264','libx265','libvpx-vp9','libaom-av1','mpeg4']))
        add('hardware','Кодирование CPU / GPU',combo(['cpu','auto','nvenc','amf','qsv']))
        add('target_mb','Целевой размер, МБ (видео — оценка)',spin(0,1048576,0,True))
        add('audio_bitrate','Аудиобитрейт, кбит/с',spin(8,512,192)); add('sample_rate','Частота аудио (0 = исходная)',spin(0,192000)); add('channels','Каналы (0 = исходные)',spin(0,2))
        add('normalize','Нормализация громкости',QCheckBox()); add('volume','Громкость, ×',spin(0,10,1,True))
        add('strip_metadata','Удалять метаданные',QCheckBox()); self.controls['strip_metadata'].setChecked(True)
        add('frame_ms','GIF: длительность кадра, мс',spin(20,60000,100)); add('frame_delays','GIF: длительности через запятую',QLineEdit()); add('loop','GIF: повторы (0 = бесконечно)',spin(0,65535))
        add('emoji_frames','VRChat: число кадров',combo(['4','16','64'])); self.controls['emoji_frames'].setCurrentText('64')
        add('pages','PDF: страницы (1,3,5-8); пусто = все',QLineEdit())
        self.advanced=Section('Дополнительные настройки',advanced,lambda:self.store.get('animations',True)); self.editor_layout.addWidget(self.advanced)
        self.extra_file=QLineEdit(); self.extra_file.setPlaceholderText('Аудио или субтитры для выбранной операции')
        row=QHBoxLayout(); row.addWidget(self.extra_file,1); row.addWidget(button('Выбрать дорожку',self.choose_extra)); self.extra_row=QWidget(); self.extra_row.setLayout(row); self.editor_layout.addWidget(self.extra_row)
        self.hint=label('','subtitle'); self.editor_layout.addWidget(self.hint)
        bottom,bl=card(); row=QHBoxLayout(); self.output=QLineEdit(self.store.get('output',str(Path.home()/'Videos'/'COKKER'))); row.addWidget(self.output,1); row.addWidget(button('Папка результата',self.choose_output)); bl.addLayout(row)
        row=QHBoxLayout(); row.addWidget(button('Сохранить пресет',self.save_preset)); row.addWidget(button('Сбросить параметры',self.reset_options)); row.addStretch(); row.addWidget(button('Добавить в очередь   Ctrl+Enter',self.enqueue,True)); bl.addLayout(row); self.editor_layout.addWidget(bottom); self.editor_layout.addStretch(); self.operation_changed()
    def operation_changed(self):
        if not hasattr(self,'format') or not hasattr(self,'extra_row'): return
        op=REGISTRY[self.operation.currentData()]; self.format.clear(); self.format.addItems(op.formats)
        self.extra_row.setVisible(op.id in ('replace_audio','add_subtitle','burn_subtitle'))
        hints={'remux':'Дорожки копируются без перекодирования. Обрезка может начинаться у ближайшего ключевого кадра. Несовместимые кодеки дадут ошибку.',
            'merge_video':'Порядок можно менять перетаскиванием. Все видео должны иметь одинаковые кодеки и параметры.',
            'replace_audio':'Первое видео + выбранное аудио. Итог ограничен более короткой дорожкой.',
            'emoji':'PNG 1024×1024: 4, 16 или 64 кадра. После сохранения загрузите его в разделе Emoji на сайте VRChat. Вход внутри приложения пока отсутствует.',
            'image':'Crop, поворот и отражение выполняются до изменения размера. Прозрачность JPEG заменяется белым фоном.',
            'pdf_pages':'Задайте страницы в нужном порядке в дополнительных настройках. Неуказанные страницы исключаются.',
            'document':'Нужен установленный LibreOffice. Формат должен соответствовать типу документа: таблица → XLSX/ODS/PDF, текст → DOCX/ODT/PDF.',
            'ebook':'Нужен установленный Calibre. DRM-защищённые книги не поддерживаются.',
            'burn_subtitle':'Видео будет перекодировано. Выберите SRT / ASS / VTT.',
            'images_gif':'Перетаскивайте файлы для изменения порядка. Длительности кадров задаются в дополнительных настройках.',
            'archive':'Файлы сохраняются в корне архива. Одинаковые имена получают числовые суффиксы.',
            'extract':'ZIP и TAR. Ссылки и пути вне целевой папки отклоняются.'}
        self.hint.setText(hints.get(op.id,'Оригиналы сохраняются. Новые файлы появятся в выбранной папке.'))
    def reset_options(self): self.apply_options(asdict(Options(format=self.format.currentText())))
    def options(self):
        o=Options(format=self.format.currentText(),quality=[82,95,55][self.quality.currentIndex()],extra_file=self.extra_file.text())
        for k,w in self.controls.items():
            val=w.isChecked() if isinstance(w,QCheckBox) else w.value() if isinstance(w,(QSpinBox,QDoubleSpinBox)) else w.currentText() if isinstance(w,QComboBox) else w.text()
            if k in ('rotate','emoji_frames'): val=int(val)
            setattr(o,k,val)
        if self.resolution.currentIndex():
            o.width,o.height=map(int,self.resolution.currentText().split(' × '))
        o.validate(); return o
    def apply_options(self,data):
        self.resolution.setCurrentIndex(0)
        self.format.setCurrentText(data.get('format',self.format.currentText()))
        self.quality.setCurrentIndex(1 if data.get('quality',82)>90 else 2 if data.get('quality',82)<65 else 0)
        for k,w in self.controls.items():
            if k not in data: continue
            v=data[k]
            if isinstance(w,QCheckBox): w.setChecked(v)
            elif isinstance(w,(QSpinBox,QDoubleSpinBox)): w.setValue(v)
            elif isinstance(w,QComboBox): w.setCurrentText(str(v))
            else: w.setText(str(v))
    def choose_files(self):
        files,_=QFileDialog.getOpenFileNames(self,'Добавить файлы'); self.add_paths(files)
    def choose_folder(self):
        path=QFileDialog.getExistingDirectory(self,'Добавить папку')
        if path: self.add_paths([path])
    def add_paths(self,paths):
        if not paths: return
        def gather():
            result=[]
            for raw in paths:
                p=Path(raw)
                if p.is_file(): result.append(str(p.resolve()))
                elif p.is_dir(): result.extend(str(f.resolve()) for f in p.rglob('*') if f.is_file() and not f.is_symlink())
            return list(dict.fromkeys(result))
        self.async_.run(gather,self.receive_paths)
    def receive_paths(self,result):
        if isinstance(result,Exception): self.error(result); return
        existing={self.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.files.count())}
        first=not existing
        for p in result:
            if p not in existing:
                item=QListWidgetItem(Path(p).name); item.setToolTip(p); item.setData(Qt.ItemDataRole.UserRole,p); self.files.addItem(item)
        if result and first:
            cat=category(result[0]); op=next((o for o in OPERATIONS if o.category==cat),OPERATIONS[0]); self.set_operation(op.id)
        self.pages.setCurrentWidget(self.editor); self.heading.setText('Подготовка файлов'); self.toast(f'Добавлено: {len(result)}. Выберите действие и параметры.')
    def input_paths(self): return [self.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.files.count())]
    def remove_inputs(self):
        for item in self.files.selectedItems(): self.files.takeItem(self.files.row(item))
    def choose_extra(self):
        p,_=QFileDialog.getOpenFileName(self,'Выбрать дорожку')
        if p:self.extra_file.setText(p)
    def choose_output(self):
        p=QFileDialog.getExistingDirectory(self,'Папка результата',self.output.text())
        if p:self.output.setText(p);self.store.set('output',p)
    def enqueue(self):
        try:
            paths=self.input_paths()
            if not paths: self.choose_files(); return
            o=self.options(); op=REGISTRY[self.operation.currentData()]
            if op.backend in ('ffmpeg','soffice','ebook-convert') and not executable(op.backend): raise ValueError('Нужный компонент не установлен. Откройте Настройки → Компоненты.')
            if not self.output.text().strip(): raise ValueError('Выберите папку результата.')
            jobs=[Job(paths if op.multiple else [p],op.id,asdict(o),self.output.text()) for p in (paths[:1] if op.multiple else paths)]
            self.queue.add(jobs); self.navigate('Очередь')
        except Exception as e:self.error(e)
    def set_operation(self,id):
        self.operation.setCurrentIndex(self.operation.findData(id)); self.pages.setCurrentWidget(self.editor); self.heading.setText(REGISTRY[id].category)
    def navigate(self,name):
        if not name:return
        self.current=name; self.heading.setText('Начнём с файла' if name=='Главная' else name)
        if name=='Главная': self.pages.setCurrentWidget(self.home)
        elif name in ('Очередь','История'): self.pages.setCurrentWidget(self.queue_page); self.refresh_queue()
        elif name=='Избранное': self.show_presets()
        elif name=='Настройки': self.show_settings()
        elif name=='О программе': self.show_about()
        else:
            op=next((o for o in OPERATIONS if o.category==name),None)
            if op:self.set_operation(op.id)
    def rebuild_tools(self,query=''):
        while self.tools_grid.count():
            item=self.tools_grid.takeAt(0)
            if item.widget():item.widget().deleteLater()
        featured=('video','remux','audio','image','images_gif','video_gif','emoji','images_pdf','pdf_merge','archive','document','ebook')
        ops=[o for o in OPERATIONS if (query.lower() in (o.label+' '+o.category).lower() if query else o.id in featured)]
        for i,op in enumerate(ops):
            b=button(op.label,lambda id=op.id:self.set_operation(id)); b.setMinimumHeight(62); self.tools_grid.addWidget(b,i//2,i%2)
    def filter_tools(self,text):
        self.pages.setCurrentWidget(self.home); self.heading.setText('Инструменты'); self.rebuild_tools(text)
    def clear_extra(self):
        while self.extra_layout.count():
            item=self.extra_layout.takeAt(0)
            if item.widget():item.widget().deleteLater()
        self.pages.setCurrentWidget(self.extra)
    def selected_jobs(self):
        ids={i.data(Qt.ItemDataRole.UserRole) for i in self.queue_list.selectedItems()}; return [j for j in self.queue.jobs if j.id in ids]
    def refresh_queue(self):
        selected={i.data(Qt.ItemDataRole.UserRole) for i in self.queue_list.selectedItems()}
        scroll=self.queue_list.verticalScrollBar().value(); self.queue_list.clear()
        jobs=list(self.queue.jobs)
        shown=[j for j in jobs if j.status=='done'] if self.current=='История' else jobs
        for j in shown:
            text=f'{STATUS[j.status]}'+(f'   {int(j.progress*100)}%' if j.status=='running' else '')+f'    {Path(j.inputs[0]).name}\n{REGISTRY[j.operation].label}'
            if j.status=='done':
                change=(1-j.after/j.before)*100 if j.before else 0
                text+=f'   •   {size(j.before)} → {size(j.after)}   ({change:+.1f}% экономии)   •   {j.elapsed:.1f} с'
            elif j.status=='failed':text+='   •   '+j.error.splitlines()[-1][:140]
            item=QListWidgetItem(text); item.setData(Qt.ItemDataRole.UserRole,j.id); item.setData(Qt.ItemDataRole.UserRole+1,j.output if j.status=='done' else ''); self.queue_list.addItem(item); item.setSelected(j.id in selected)
        self.queue_list.verticalScrollBar().setValue(scroll)
        active=[j for j in jobs if j.status in ('waiting','running')]; complete=sum(j.status=='done' for j in jobs)
        pct=round(sum(j.progress if j.status=='running' else 1 if j.status=='done' else 0 for j in jobs)/max(len(jobs),1)*100)
        self.progress.setValue(pct); self.progress.setFormat(f'{complete} / {len(jobs)} готовы  •  {pct}%')
        self.setWindowTitle((f'{pct}% — ' if active else '')+'COKKER Converter')
        if hasattr(self,'tray'):self.tray.setToolTip(f'COKKER Converter\n{len(active)} задач • {pct}%' if active else 'COKKER Converter — готов к работе')
    def retry(self):self.queue.retry([j.id for j in self.selected_jobs()])
    def cancel(self):self.queue.cancel([j.id for j in self.selected_jobs()])
    def remove(self):self.queue.remove([j.id for j in self.selected_jobs()])
    def result_paths(self):return [j.output for j in self.selected_jobs() if j.status=='done' and Path(j.output).exists()]
    def open_result(self):
        for p in self.result_paths():QDesktopServices.openUrl(QUrl.fromLocalFile(p))
    def open_folder(self):
        paths=self.result_paths(); p=str(Path(paths[0]).parent) if paths else self.output.text(); QDesktopServices.openUrl(QUrl.fromLocalFile(p))
    def copy_results(self):
        mime=QMimeData(); mime.setUrls([QUrl.fromLocalFile(p) for p in self.result_paths()]); QApplication.clipboard().setMimeData(mime); self.toast('Файлы скопированы в буфер обмена.')
    def copy_image(self):
        paths=self.result_paths()
        if paths:
            pix=QPixmap(paths[0])
            if pix.isNull():self.error(ValueError('Этот результат не является изображением.'));return
            QApplication.clipboard().setPixmap(pix); self.toast('Изображение скопировано.')
    def error_details(self):
        jobs=self.selected_jobs()
        if jobs and jobs[0].error:self.error(RuntimeError(jobs[0].error))
    def completed(self,id):
        j=next((j for j in self.queue.jobs if j.id==id),None)
        if j and self.store.get('notifications',True) and self.tray.isVisible():self.tray.showMessage('COKKER Converter',STATUS[j.status]+' — '+Path(j.inputs[0]).name)
    def recovery(self):
        ids=[j.id for j in self.queue.jobs if j.status=='interrupted']
        if QMessageBox.question(self,'Восстановление',f'Найдено незавершённых задач: {len(ids)}. Запустить заново?')==QMessageBox.StandardButton.Yes:self.queue.retry(ids)
        else:self.navigate('Очередь')
    def paste(self):
        if not self.store.get('clipboard',True):return
        mime=QApplication.clipboard().mimeData()
        if mime.hasUrls():self.add_paths([u.toLocalFile() for u in mime.urls() if u.isLocalFile()])
        elif mime.hasImage():
            folder=self.store.root/'clipboard'; folder.mkdir(exist_ok=True); p=folder/(uuid.uuid4().hex+'.png'); QApplication.clipboard().image().save(str(p)); self.add_paths([str(p)])
    def save_preset(self):
        try:
            data=asdict(self.options()); data.pop('extra_file'); name,ok=QInputDialog.getText(self,'Пресет','Название операции')
            if ok and name:
                items=self.presets.all(); items.append({'schemaVersion':1,'presetName':name,'category':REGISTRY[self.operation.currentData()].category,'operation':self.operation.currentData(),'parameters':data}); self.presets.save(items); self.toast('Пресет сохранён в Избранном.')
        except Exception as e:self.error(e)
    def show_presets(self):
        self.clear_extra(); self.extra_layout.addWidget(label('Сохраняй операции целиком и переноси их через JSON. Порядок можно менять перетаскиванием.','subtitle'))
        listing=QListWidget(); listing.setDragDropMode(QListWidget.DragDropMode.InternalMove); listing.setMinimumHeight(300)
        for p in self.presets.all():
            item=QListWidgetItem('★  '+p['presetName']); item.setData(Qt.ItemDataRole.UserRole,p); listing.addItem(item)
        def persist():self.presets.save([listing.item(i).data(Qt.ItemDataRole.UserRole) for i in range(listing.count())])
        listing.model().rowsMoved.connect(lambda *args:persist())
        def use():
            if listing.currentItem():
                p=listing.currentItem().data(Qt.ItemDataRole.UserRole); self.set_operation(p['operation']); self.apply_options(p['parameters'])
        def delete():
            if listing.currentRow()>=0:listing.takeItem(listing.currentRow());persist()
        def duplicate():
            if listing.currentItem():
                p=dict(listing.currentItem().data(Qt.ItemDataRole.UserRole));p['presetName']+=' — копия';items=self.presets.all()+[p];self.presets.save(items);self.show_presets()
        def export():
            path,_=QFileDialog.getSaveFileName(self,'Экспорт всех пресетов','COKKER-presets.json','JSON (*.json)')
            if path:
                try:self.presets.export_file(path,self.presets.all())
                except Exception as e:self.error(e)
        def import_():
            path,_=QFileDialog.getOpenFileName(self,'Импорт','', 'JSON (*.json)')
            if path:
                try:self.presets.import_file(path);self.show_presets()
                except Exception as e:self.error(e)
        self.extra_layout.addWidget(listing);row=QWidget();rl=QHBoxLayout(row)
        for text,fn in [('Применить / изменить',use),('Дублировать',duplicate),('Удалить',delete),('Экспорт JSON',export),('Импорт JSON',import_)]:rl.addWidget(button(text,fn))
        self.extra_layout.addWidget(row);self.extra_layout.addStretch()
    def show_settings(self):
        self.clear_extra()
        box,bl=card();bl.addWidget(label('Интерфейс и обработка','title'));form=QFormLayout()
        theme=combo(['system','dark','light']);theme.setCurrentText(self.store.get('theme','dark'));theme.currentTextChanged.connect(lambda v:(self.store.set('theme',v),self.apply_theme()));form.addRow('Тема',theme)
        concurrency=spin(1,4,self.store.get('concurrency',1));concurrency.valueChanged.connect(lambda v:self.store.set('concurrency',v));form.addRow('Параллельные задачи',concurrency)
        bl.addLayout(form)
        for key,text,default in [('animations','Анимация раскрытия настроек',True),('sleep_block','Не давать Windows заснуть во время обработки',True),('clipboard','Ctrl+V: добавлять файлы и изображения',True),('notifications','Уведомления о завершении',True),('close_tray','Закрывать окно в трей',False),('minimize_tray','Сворачивать в трей',False)]:
            w=QCheckBox(text);w.setChecked(self.store.get(key,default));w.toggled.connect(lambda v,k=key:self.store.set(k,v));bl.addWidget(w)
        self.extra_layout.addWidget(box)
        box,bl=card();bl.addWidget(label('Запуск с Windows','title'));auto=QCheckBox('Запускать вместе с Windows');tray=QCheckBox('При автозапуске открывать сразу в трее');auto.setChecked(self.store.get('autostart',False));tray.setChecked(self.store.get('autostart_tray',False));tray.setEnabled(auto.isChecked());auto.setEnabled(os.name=='nt')
        def save_startup():
            try:
                startup(auto.isChecked(),tray.isChecked());self.store.set('autostart',auto.isChecked());self.store.set('autostart_tray',tray.isChecked());tray.setEnabled(auto.isChecked())
            except Exception as e:
                auto.blockSignals(True);auto.setChecked(self.store.get('autostart',False));auto.blockSignals(False);self.error(e)
        auto.toggled.connect(save_startup);tray.toggled.connect(save_startup);bl.addWidget(auto);bl.addWidget(tray);self.extra_layout.addWidget(box)
        box,bl=card();bl.addWidget(label('Компоненты','title'));bl.addWidget(label('FFmpeg и ffprobe можно положить в папку components рядом с EXE. LibreOffice и Calibre обнаруживаются после установки.','subtitle'))
        for name in ('ffmpeg','ffprobe','soffice','ebook-convert'):
            p=executable(name);row=QHBoxLayout();row.addWidget(label(name+'  —  '+('найден' if p else 'не установлен')),1)
            if p: row.addWidget(label(p,'subtitle'))
            else:row.addWidget(button('Официальный сайт',lambda n=name:QDesktopServices.openUrl(QUrl(URLS.get(n,URLS['ffmpeg'])))))
            bl.addLayout(row)
        self.extra_layout.addWidget(box)
        self.extra_layout.addWidget(button('Проверить обновления GitHub',self.check_update));self.extra_layout.addWidget(label('Обычные пользовательские файлы обрабатываются локально на компьютере. Приложение не отправляет их на серверы. Обновления проверяются только по нажатию кнопки.','subtitle'));self.extra_layout.addStretch()
    def show_about(self):
        self.clear_extra();self.extra_layout.addWidget(label('COKKER Converter  '+__version__,'title'));self.extra_layout.addWidget(label('Локальная обработка видео, аудио, изображений и документов.\nПредварительная версия: проверяйте результат перед удалением исходников.'))
        self.extra_layout.addWidget(button('GitHub',lambda:QDesktopServices.openUrl(QUrl(REPO))));self.extra_layout.addWidget(button('VRChat: открыть сайт для загрузки Emoji',lambda:QDesktopServices.openUrl(QUrl('https://vrchat.com/home'))));self.extra_layout.addStretch()
    def apply_theme(self):
        theme=self.store.get('theme','dark')
        if theme=='system':theme='dark' if QApplication.styleHints().colorScheme()==Qt.ColorScheme.Dark else 'light'
        QApplication.instance().setStyleSheet(stylesheet(theme))
    def check_update(self):
        self.toast('Проверяю GitHub Releases…')
        def done(value):
            if isinstance(value,Exception):self.error(value)
            else:
                version,url=value
                if version.lstrip('v')==__version__:self.toast('Установлена последняя опубликованная версия.')
                elif QMessageBox.question(self,'Обновление',f'На GitHub опубликована версия {version}. Открыть?')==QMessageBox.StandardButton.Yes:QDesktopServices.openUrl(QUrl(url))
        self.async_.run(latest_release,done)
    def inspect(self):
        paths=self.input_paths()
        if not paths:return
        p=paths[0];self.toast('Читаю информацию о файле…')
        def read():
            if category(p)=='Изображения':
                from PIL import Image
                with Image.open(p) as im:return f'{im.format} • {im.width} × {im.height}\nКадров: {getattr(im,"n_frames",1)}\n{size(Path(p).stat().st_size)}'
            info=Engine().probe(p);f=info.get('format',{});lines=[f"Размер: {size(int(f.get('size',0)))}",f"Длительность: {float(f.get('duration',0)):.2f} с"]
            for s in info.get('streams',[]):lines.append(f"#{s['index']}  {s.get('codec_type')}  {s.get('codec_name')}  {s.get('width','')} × {s.get('height','')}  {s.get('r_frame_rate','')}")
            return '\n'.join(lines)
        self.async_.run(read,lambda v:self.error(v) if isinstance(v,Exception) else QMessageBox.information(self,'Информация',v))
    def preview(self):
        paths=self.input_paths()
        if not paths:return
        p=paths[0];self.toast('Готовлю предпросмотр…')
        def prepare():
            if category(p)=='Изображения':return p
            cache=self.store.root/'preview';cache.mkdir(exist_ok=True);out=cache/(uuid.uuid4().hex+'.png')
            ff=executable('ffmpeg')
            if not ff:raise ValueError('Нужен FFmpeg.')
            Engine().runner.run([ff,'-v','error','-i',p,'-frames:v','1','-y',str(out)])
            return str(out)
        def show(v):
            if isinstance(v,Exception):self.error(v);return
            d=QDialog(self);d.setWindowTitle('Preview / Crop — выделите рамку мышью');d.resize(760,580);l=QVBoxLayout(d);canvas=CropCanvas();canvas.set_source(v);l.addWidget(canvas,1)
            field=QLineEdit(self.controls['crop'].text());canvas.selected.connect(field.setText);l.addWidget(label('X,Y,ширина,высота исходного изображения'));l.addWidget(field)
            buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel);buttons.accepted.connect(d.accept);buttons.rejected.connect(d.reject);l.addWidget(buttons)
            if d.exec():self.controls['crop'].setText(field.text())
        self.async_.run(prepare,show)
    def build_tray(self):
        self.tray=QSystemTrayIcon(self.icon,self);menu=QMenu(self)
        for text,fn in [('Открыть',self.reveal),('Добавить файлы',self.choose_files),('Папка результатов',self.open_folder),('Пауза / продолжить очередь',self.pause_queue),('Отменить активные',lambda:self.queue.cancel(list(self.queue.active))),('Настройки',lambda:(self.reveal(),self.navigate('Настройки'))),('Выход',self.exit_app)]:
            a=menu.addAction(text);a.triggered.connect(fn)
        self.tray.setContextMenu(menu);self.tray.activated.connect(lambda reason:self.reveal() if reason==QSystemTrayIcon.ActivationReason.DoubleClick else None);self.tray.messageClicked.connect(lambda:(self.reveal(),self.navigate('Очередь')))
        if QSystemTrayIcon.isSystemTrayAvailable():self.tray.show()
    def pause_queue(self):self.queue.paused=not self.queue.paused;self.queue.pump();self.toast('Новые задачи приостановлены.' if self.queue.paused else 'Очередь продолжена.')
    def reveal(self):self.showNormal();self.raise_();self.activateWindow()
    def exit_app(self):
        if self.queue.active and QMessageBox.question(self,'Выход','Отменить активную обработку и выйти?')!=QMessageBox.StandardButton.Yes:return
        self.exiting=True;self.close()
    def closeEvent(self,event):
        if not self.exiting and self.store.get('close_tray',False) and self.tray.isVisible():
            self.hide();event.ignore()
            if not self.store.get('tray_notice',False):self.tray.showMessage('COKKER Converter','Приложение продолжает работать в трее. Для выхода используйте меню значка.');self.store.set('tray_notice',True)
            return
        if not self.exiting and self.queue.active:
            if QMessageBox.question(self,'Выход','Отменить активную обработку и выйти?')!=QMessageBox.StandardButton.Yes:event.ignore();return
        self.save_window();self.queue.shutdown();self.async_.pool.shutdown(wait=False,cancel_futures=True);self.tray.hide();self.store.close();event.accept();QApplication.instance().quit()
    def changeEvent(self,event):
        if event.type()==event.Type.WindowStateChange and self.isMinimized() and self.store.get('minimize_tray',False) and self.tray.isVisible():QTimer.singleShot(0,self.hide)
        super().changeEvent(event)
    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'save_timer'):self.save_timer.start(500)
    def save_window(self):self.store.set('geometry',[self.width(),self.height()])
    def eventFilter(self,obj,event):
        if event.type()==event.Type.Wheel and hasattr(self,'pages'):
            from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QScrollArea
            if isinstance(obj,(QAbstractSpinBox,QComboBox)) and obj is not QApplication.focusWidget():
                parent=obj.parentWidget()
                while parent and not isinstance(parent,QScrollArea): parent=parent.parentWidget()
                if parent and parent.isVisible():
                    bar=parent.verticalScrollBar(); bar.setValue(bar.value()-event.angleDelta().y()); return True
        return super().eventFilter(obj,event)
    def dragEnterEvent(self,e):
        if e.mimeData().hasUrls():e.acceptProposedAction()
    def dropEvent(self,e):self.add_paths([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]);e.acceptProposedAction()
    def toast(self,text):
        self.notice.setText(text);self.notice.show();QTimer.singleShot(7000,self.notice.hide)
    def error(self,e):
        msg=QMessageBox(self);msg.setIcon(QMessageBox.Icon.Warning);msg.setWindowTitle('COKKER Converter');msg.setText('Не удалось выполнить действие');msg.setInformativeText(str(e).splitlines()[-1][:300]);msg.setDetailedText(str(e));msg.exec()
