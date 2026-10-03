import json, os, sys, uuid, time, shutil, subprocess, threading, tempfile, logging
from pathlib import Path
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QUrl, QMimeData, QPropertyAnimation, QEasingCurve, QSize, QProcess
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QDesktopServices, QPixmap, QIcon, QPainter, QColor
from PySide6.QtWidgets import (QApplication,QMainWindow,QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QFormLayout,QLayout,QLabel,QPushButton,QListWidget,QListWidgetItem,QStackedWidget,QScrollArea,QFrame,QComboBox,QSpinBox,QDoubleSpinBox,QLineEdit,QCheckBox,QFileDialog,QMessageBox,QInputDialog,QProgressBar,QPlainTextEdit,QSystemTrayIcon,QMenu,QDialog,QDialogButtonBox,QSplitter,QGraphicsOpacityEffect,QSizePolicy,QSlider)
from . import __version__
from .models import Options,Job
from .registry import OPERATIONS,REGISTRY,category,compatible_operations,file_kind
from .icons import icon_for
from .storage import Store,Presets
from .queue import Queue
from .engine import Engine
from .platform_services import executable,URLS,REPO,startup
from .updater import check_release,download,prepare_portable
from .style import stylesheet
from .widgets import FileList,Results,CropCanvas,Section,AnimatedButton
from .media_preview import MediaPreview
from .media_info import source_info

class Async(QObject):
    result=Signal(object,object)
    def __init__(self,parent=None):
        super().__init__(parent); self.pool=ThreadPoolExecutor(max_workers=2); self.result.connect(self.deliver)
    def deliver(self,callback,value):
        try: callback(value)
        except Exception as error:
            logging.exception('Ошибка обработки результата фоновой задачи')
            if self.parent(): self.parent().error(error)
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
    b=AnimatedButton(text,animate=lambda:QApplication.instance().property('animations') is not False)
    def invoke(checked=False):
        try: fn()
        except Exception as error:
            logging.exception('Ошибка действия «%s»',text)
            owner=b.window()
            if hasattr(owner,'error'):
                QTimer.singleShot(0,lambda issue=error,window=owner:window.error(issue))
    b.clicked.connect(invoke)
    if primary: b.setObjectName('primary')
    return b

def spin(lo,hi,value=0,decimal=False):
    w=QDoubleSpinBox() if decimal else QSpinBox(); w.setRange(lo,hi); w.setValue(value); w.setFocusPolicy(Qt.FocusPolicy.StrongFocus); return w

def combo(items):
    w=QComboBox(); w.addItems(items); w.setFocusPolicy(Qt.FocusPolicy.StrongFocus); return w

def card():
    w=QFrame(); w.setObjectName('card'); w.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Minimum)
    l=QVBoxLayout(w); l.setSpacing(12); return w,l

STATUS={'waiting':'Ожидает','running':'Обработка','interrupted':'Прервано — восстановить?','done':'Готово','cancelled':'Отменено','failed':'Ошибка'}
SECTION_KINDS={'Видео':{'video'},'Аудио':{'audio','video'},'Изображения':{'image'},
               'Документы':{'document'},'PDF':{'pdf','image'},'Архивы':None,
               'Электронные книги':{'ebook'},'VRChat':{'video','image'}}
COMPONENTS=(('ffmpeg','FFmpeg + ffprobe','Gyan.FFmpeg'),('soffice','LibreOffice','TheDocumentFoundation.LibreOffice'),('ebook-convert','Calibre','calibre.calibre'))

def size(n):
    for unit in ('Б','КБ','МБ','ГБ','ТБ'):
        if n<1024: return f'{n:.1f} {unit}'
        n/=1024
    return f'{n:.1f} ПБ'

class Window(QMainWindow):
    update_progress=Signal(int)
    def __init__(self,store=None):
        super().__init__(); self.store=store or Store(); self.presets=Presets(self.store); self.queue=Queue(self.store); self.async_=Async(self)
        self.setWindowTitle('COKKER Converter'); self.resize(1180,820); self.setMinimumSize(840,600); self.setAcceptDrops(True)
        self.exiting=False; self.current='Главная'; self.queue_rows={}; self.controls={}; self.notice_timer=QTimer(self)
        self._source_token=0; self._preset_active=False; self._format_pinned=False; self._install_process=None
        self._source_ratio=None;self._source_bytes=0;self._source_duration=0;self._source_has_audio=False;self._syncing_dimensions=False;self._syncing_size=False
        self._section_filter=None;self._immediate_ids=set();self._preview_token=0
        self._install_output='';self._install_cancelled=False;self._install_tasks=[]
        self._release=None;self._update_checked=False;self._update_checking=False;self._update_busy=False;self._update_status='Проверка ещё не выполнялась.'
        self._update_ready=None;self._update_ready_version=None;self._update_ready_kind=None
        self._update_cancel=threading.Event();self._update_percent=0
        self.update_progress.connect(self.on_update_progress)
        QApplication.instance().setProperty('animations',self.store.get('animations',True))
        self.notice_timer.setSingleShot(True);self.notice_timer.timeout.connect(self.notice_timer_done)
        self.build_icon(); self.setWindowIcon(self.icon); self.build(); self.build_tray(); self.apply_theme()
        self.update_timer=QTimer(self);self.update_timer.timeout.connect(lambda:self.check_update(automatic=True) if self.store.get('update_auto_check',True) else None)
        self.update_timer.start(60*60*1000)
        if self.store.get('update_auto_check',True) and os.name=='nt' and os.environ.get('QT_QPA_PLATFORM')!='offscreen':
            QTimer.singleShot(5000,lambda:self.check_update(automatic=True))
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
        base=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))
        pix=QPixmap(str(base/'assets'/'logo.png'))
        self.icon=QIcon(pix) if not pix.isNull() else icon_for('vr')
    def build(self):
        central=QWidget(); self.setCentralWidget(central); root=QHBoxLayout(central); root.setContentsMargins(16,16,16,16); root.setSpacing(18)
        side=QFrame();side.setObjectName('sidebar');side.setFixedWidth(232)
        sl=QVBoxLayout(side);sl.setContentsMargins(13,15,13,15);sl.setSpacing(12)
        branding=QWidget();brand_row=QHBoxLayout(branding);brand_row.setContentsMargins(3,0,3,0);brand_row.setSpacing(10)
        logo=QLabel();logo.setPixmap(self.icon.pixmap(QSize(46,46)));logo.setFixedSize(46,46);brand_row.addWidget(logo)
        brand_row.addWidget(label('COKKER\nConverter','brand'),1);sl.addWidget(branding)
        self.nav=QListWidget(); self.nav.setObjectName('nav')
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.setIconSize(QSize(20,20));self.nav.setSpacing(2)
        for name in ('Главная','Избранное','Очередь','История','Видео','Аудио','Изображения','Документы','PDF','Архивы','Электронные книги','VRChat','Настройки','О программе'):
            item=QListWidgetItem(icon_for(name),name);item.setSizeHint(QSize(0,40));self.nav.addItem(item)
        self.nav.setCurrentRow(0)
        self.nav.currentTextChanged.connect(self.navigate);sl.addWidget(self.nav)
        sl.addWidget(label('●  Файлы остаются на устройстве','sidebarHint'));root.addWidget(side)
        main=QWidget(); ml=QVBoxLayout(main); ml.setContentsMargins(0,2,0,0); ml.setSpacing(16)
        top=QHBoxLayout(); self.heading=label('Начнём с файла','title'); top.addWidget(self.heading,1)
        self.update_badge=button('',lambda:self.navigate('Настройки'));self.update_badge.setObjectName('updateBadge')
        self.update_badge.setMaximumWidth(188);self.update_badge.hide();top.addWidget(self.update_badge)
        self.search=QLineEdit(); self.search.setPlaceholderText('Найти инструмент   Ctrl+F'); self.search.setMaximumWidth(260);self.search.setMinimumWidth(130); self.search.textChanged.connect(self.filter_tools); top.addWidget(self.search); ml.addLayout(top)
        self.notice=label(''); self.notice.setStyleSheet('color:#ff9c56;padding:8px;'); self.notice.hide(); ml.addWidget(self.notice)
        self.pages=QStackedWidget(); ml.addWidget(self.pages,1); root.addWidget(main,1)
        self.home,self.home_layout=self.page(); self.tools_widget=QWidget(); self.tools_grid=QGridLayout(self.tools_widget); self.tools_grid.setContentsMargins(0,0,0,0)
        self.home_layout.addWidget(label('Перетащи файлы — подходящие действия появятся автоматически.','subtitle'))
        drop,dl=card(); dl.addWidget(label('Добавь видео, музыку, изображения или документы','title'))
        dl.addWidget(label('Перетаскивание файлов и папок • Ctrl+V из буфера обмена','subtitle'))
        actions=QHBoxLayout(); actions.addWidget(button('Выбрать файлы',self.choose_files,True)); actions.addWidget(button('Добавить папку',self.choose_folder)); actions.addStretch(); dl.addLayout(actions); self.home_layout.addWidget(drop)
        quick,quick_layout=card();quick_layout.addWidget(label('Быстрый старт','title'))
        shortcuts=QHBoxLayout();shortcuts.addWidget(button('PNG → JPG  ★',lambda:self.use_quick('image','jpg')))
        shortcuts.addWidget(button('Фото → 1920 × 1080  ★',lambda:self.use_quick('image','jpg',1920,1080)))
        shortcuts.addWidget(button('Все пресеты →',lambda:self.navigate('Избранное')))
        quick_layout.addLayout(shortcuts);self.home_layout.addWidget(quick)
        self.home_layout.addWidget(self.tools_widget); self.home_layout.addStretch()
        self.editor,self.editor_layout=self.page(); self.build_editor()
        self.queue_page,self.ql=self.page();self.ql.addWidget(label('Текущие задачи','title'))
        self.queue_list=Results(); self.queue_list.setMinimumHeight(210); self.ql.addWidget(self.queue_list,1)
        self.progress=QProgressBar(); self.ql.addWidget(self.progress)
        self.queue_preview,self.queue_preview_mode=self.build_result_preview(self.ql)
        row=QGridLayout();row.setSpacing(8)
        for i,(text,fn) in enumerate([('Открыть',self.open_result),('Папка',self.open_folder),('Копировать файлы',self.copy_results),('Копировать изображение',self.copy_image),('Повторить',self.retry),('Отменить',self.cancel),('Убрать',self.remove)]):row.addWidget(button(text,fn),i//2,i%2)
        self.ql.addLayout(row); self.ql.addWidget(button('Подробности ошибки',self.error_details)); self.queue_list.itemDoubleClicked.connect(lambda _:self.open_result())
        self.queue_list.currentItemChanged.connect(lambda *_:self.refresh_result_preview())
        self.history_page,self.hl=self.page();self.hl.addWidget(label('Завершённые преобразования','title'))
        self.history_summary=label('Пока нет готовых результатов.','subtitle');self.hl.addWidget(self.history_summary)
        self.history_list=Results();self.history_list.setMinimumHeight(220);self.hl.addWidget(self.history_list,1)
        self.history_preview,self.history_preview_mode=self.build_result_preview(self.hl)
        self.history_list.currentItemChanged.connect(lambda *_:self.refresh_result_preview())
        self.history_list.itemDoubleClicked.connect(lambda _:self.open_result())
        history_actions=QHBoxLayout();history_actions.addWidget(button('Открыть результат',self.open_result,True));history_actions.addWidget(button('Папка результата',self.open_folder));history_actions.addWidget(button('Убрать запись',self.remove));self.hl.addLayout(history_actions)
        self.extra,self.extra_layout=self.page()
        self.rebuild_tools()
    def build_result_preview(self,layout):
        box,body=card();body.addWidget(label('Результат · до / после','title'))
        mode=combo(['До','После']);mode.setToolTip('Для видео и GIF переключает исходный и готовый файл. Для изображения доступно сравнение ползунком.');body.addWidget(mode)
        preview=MediaPreview();body.addWidget(preview);layout.addWidget(box)
        mode.currentIndexChanged.connect(lambda *_:self.refresh_result_preview())
        return preview,mode
    def page(self):
        content=QWidget(); layout=QVBoxLayout(content); layout.setContentsMargins(4,6,12,18); layout.setSpacing(16)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(content); self.pages.addWidget(scroll); return scroll,layout
    def build_editor(self):
        self.editor_layout.addWidget(label('1  Исходные файлы','subtitle'))
        self.files=FileList(); self.files.setMaximumHeight(148); self.files.filesDropped.connect(self.add_paths); self.files.itemDoubleClicked.connect(lambda _:self.inspect()); self.files.currentItemChanged.connect(lambda *_:self.update_source()); self.editor_layout.addWidget(self.files)
        self.input_summary=label('Добавь файлы — покажу доступные действия.','subtitle');self.editor_layout.addWidget(self.input_summary)
        preview_card,preview_layout=card(); preview_layout.addWidget(label('Предпросмотр выбранного файла','title'))
        self.media_preview=MediaPreview(); preview_layout.addWidget(self.media_preview)
        self.editor_layout.addWidget(preview_card)
        self.compare_video_button=button('Сравнить текущий кадр до / после',self.compare_video_frame)
        self.editor_layout.addWidget(self.compare_video_button)
        row=QGridLayout();row.setSpacing(8)
        for i,(text,fn) in enumerate([('Добавить',self.choose_files),('Папка',self.choose_folder),('Удалить выбранные',self.remove_inputs),('Информация',self.inspect),('Preview / Crop',self.preview)]):row.addWidget(button(text,fn),i//2,i%2)
        self.editor_layout.addLayout(row)
        basic,bl=card(); form=QFormLayout(); form.setSpacing(12); self.operation=QComboBox()
        self.operation.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.operation.setMinimumContentsLength(17);self.operation.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        for op in OPERATIONS: self.operation.addItem(icon_for(op.category),op.label,op.id)
        self.operation.currentIndexChanged.connect(self.operation_changed)
        self.operation.activated.connect(lambda *_:setattr(self,'_requested_operation',self.operation.currentData()))
        form.addRow('Действие',self.operation); self.format=QComboBox(); self.format.currentTextChanged.connect(self.update_visible_options)
        self.format.activated.connect(lambda *_:setattr(self,'_format_pinned',True));form.addRow('Формат',self.format)
        self.quality=combo(['Сбалансированное','Высокое качество','Максимальное сжатие']); form.addRow('Качество',self.quality)
        self.resolution=combo(['Оригинальное','3840 × 2160','2560 × 1440','1920 × 1080','1280 × 720','1080 × 1920','1080 × 1080','512 × 512'])
        form.addRow('Готовый размер',self.resolution); self.basic_form=form;bl.addLayout(form); self.editor_layout.addWidget(basic)
        advanced=QWidget(); af=QFormLayout(advanced); af.setSpacing(10); self.advanced_form=af
        def add(key,text,w): self.controls[key]=w; af.addRow(text,w)
        add('width','Ширина (0 = авто)',spin(0,16384)); add('height','Высота (0 = авто)',spin(0,16384))
        self.lock_ratio=QCheckBox('Сохранять пропорции исходника');self.lock_ratio.setChecked(True)
        self.lock_ratio.setToolTip('При изменении ширины автоматически пересчитывает высоту, и наоборот.')
        af.addRow('',self.lock_ratio)
        self.controls['width'].valueChanged.connect(lambda value:self.dimension_changed('width',value))
        self.controls['height'].valueChanged.connect(lambda value:self.dimension_changed('height',value))
        self.resolution.currentIndexChanged.connect(self.choose_resolution)
        add('scale_mode','Размер: вписать / заполнить / растянуть',combo(['fit','fill','stretch']))
        add('no_upscale','Не увеличивать исходник',QCheckBox()); self.controls['no_upscale'].setChecked(True)
        add('start','Начало, секунд',spin(0,999999,0,True)); add('end','Конец, секунд (0 = до конца)',spin(0,999999,0,True))
        add('crop','Crop: X,Y,ширина,высота',QLineEdit()); add('rotate','Поворот по часовой стрелке',combo(['0','90','180','270']))
        add('flip','Отражение',combo(['none','horizontal','vertical'])); add('fps','FPS (0 = исходный)',spin(0,240,0,True)); add('speed','Скорость, ×',spin(.1,16,1,True))
        add('codec','Видеокодек',combo(['auto','libx264','libx265','libvpx-vp9','libaom-av1','mpeg4']))
        add('hardware','Кодирование CPU / GPU',combo(['cpu','auto','nvenc','amf','qsv']))
        target=spin(0,1048576,0,True);target.setDecimals(6);target.setSingleStep(.1)
        add('target_mb','Целевой размер, МБ (видео — оценка)',target)
        self.size_slider=QSlider(Qt.Orientation.Horizontal);self.size_slider.setRange(5,100);self.size_slider.setValue(100)
        self.size_slider.setEnabled(False)
        self.size_slider.setToolTip('Перетащите для выбора размера относительно исходного файла. 100% — без ограничения. Для фото применяется сжатие, а если его недостаточно — уменьшение разрешения. Для видео автоматически рассчитывается битрейт.')
        self.size_hint=label('Добавьте файл, чтобы выбрать размер результата.','subtitle')
        self.size_row=QFrame();self.size_row.setObjectName('sizePanel')
        size_layout=QVBoxLayout(self.size_row);size_layout.setContentsMargins(15,12,15,12);size_layout.setSpacing(8)
        size_heading=QHBoxLayout();size_heading.addWidget(label('Размер результата','sizeTitle'),1)
        self.size_percent=label('Без ограничения','sizePercent');size_heading.addWidget(self.size_percent)
        size_layout.addLayout(size_heading);size_layout.addWidget(self.size_slider);size_layout.addWidget(self.size_hint)
        bl.addWidget(self.size_row)
        self.size_slider.valueChanged.connect(self.size_slider_changed)
        target.valueChanged.connect(self.target_size_changed)
        add('audio_bitrate','Аудиобитрейт, кбит/с',spin(8,512,192))
        self.controls['audio_bitrate'].valueChanged.connect(lambda *_:self.update_size_hint())
        add('sample_rate','Частота аудио (0 = исходная)',spin(0,192000)); add('channels','Каналы (0 = исходные)',spin(0,2))
        add('normalize','Нормализация громкости',QCheckBox()); add('volume','Громкость, ×',spin(0,10,1,True))
        add('strip_metadata','Удалять метаданные',QCheckBox()); self.controls['strip_metadata'].setChecked(True)
        add('frame_ms','GIF: длительность кадра, мс',spin(20,60000,100)); add('frame_delays','GIF: длительности через запятую',QLineEdit()); add('loop','GIF: повторы (0 = бесконечно)',spin(0,65535))
        add('emoji_frames','VRChat: число кадров',combo(['4','16','64'])); self.controls['emoji_frames'].setCurrentText('64')
        add('pages','PDF: страницы (1,3,5-8); пусто = все',QLineEdit())
        self.advanced=Section('Дополнительные настройки',advanced,lambda:self.store.get('animations',True)); self.editor_layout.addWidget(self.advanced)
        self.set_option_help()
        self.preview_timer=QTimer(self);self.preview_timer.setSingleShot(True);self.preview_timer.timeout.connect(self.refresh_live_preview)
        for key in ('width','height','scale_mode','no_upscale','crop','rotate','flip','fps','target_mb','start','end'):
            w=self.controls[key]
            if isinstance(w,QCheckBox):w.toggled.connect(lambda *_:self.preview_timer.start(180))
            elif isinstance(w,QComboBox):w.currentTextChanged.connect(lambda *_:self.preview_timer.start(180))
            elif isinstance(w,QLineEdit):w.textChanged.connect(lambda *_:self.preview_timer.start(180))
            else:w.valueChanged.connect(lambda *_:self.preview_timer.start(180))
        self.format.currentTextChanged.connect(lambda *_:self.preview_timer.start(180))
        self.quality.currentIndexChanged.connect(lambda *_:self.preview_timer.start(180))
        self.extra_file=QLineEdit(); self.extra_file.setPlaceholderText('Аудио или субтитры для выбранной операции')
        row=QHBoxLayout(); row.addWidget(self.extra_file,1); row.addWidget(button('Выбрать дорожку',self.choose_extra)); self.extra_row=QWidget(); self.extra_row.setLayout(row); self.editor_layout.addWidget(self.extra_row)
        self.hint=label('','subtitle'); self.editor_layout.addWidget(self.hint)
        bottom,bl=card(); row=QHBoxLayout(); self.output=QLineEdit(self.store.get('output',str(Path.home()/'Videos'/'COKKER'))); row.addWidget(self.output,1); row.addWidget(button('Папка результата',self.choose_output)); bl.addLayout(row)
        row=QGridLayout();row.setSpacing(8)
        row.addWidget(button('Сохранить пресет',self.save_preset),0,0)
        row.addWidget(button('★  В избранное',self.add_favorite),0,1)
        row.addWidget(button('Сбросить параметры',self.reset_options),1,0,1,2)
        self.enqueue_button=button('Добавить в очередь   Ctrl+Enter',self.enqueue)
        row.addWidget(self.enqueue_button,2,0)
        self.convert_button=button('Конвертировать сейчас',self.convert_now,True);row.addWidget(self.convert_button,2,1)
        bl.addLayout(row); self.editor_layout.addWidget(bottom); self.editor_layout.addStretch(); self.operation_changed()
    def operation_changed(self):
        if not hasattr(self,'format') or not hasattr(self,'extra_row'): return
        op=REGISTRY[self.operation.currentData()];previous=self.format.currentText()
        self.format.clear(); self.format.addItems(op.formats)
        if previous in op.formats:self.format.setCurrentText(previous)
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
        self.update_visible_options()
        self.compare_video_button.setVisible(op.id in ('video','burn_subtitle','video_gif'))
        if hasattr(self,'enqueue_button') and self.files.count():
            count=1 if op.multiple else self.files.count()
            self.enqueue_button.setText(f'Добавить в очередь: {count} задач(и)   Ctrl+Enter')
    def set_option_help(self):
        help_text={
            'width':'Ширина исходного кадра подставляется автоматически. Измените значение для результата; 0 отключает ограничение.',
            'height':'Высота исходного кадра подставляется автоматически. Измените значение для результата; 0 отключает ограничение.',
            'scale_mode':'fit сохраняет пропорции, fill обрезает лишнее, stretch растягивает изображение.',
            'no_upscale':'Если включено, маленькое изображение не будет увеличено до выбранного размера.',
            'start':'Начальная позиция видео или аудио в секундах. 0 означает начало файла.',
            'end':'Конечная позиция в секундах. 0 означает до конца файла.',
            'crop':'Координаты и размер области исходного изображения: X,Y,ширина,высота. Выделить область можно кнопкой Preview / Crop.',
            'rotate':'Повернуть изображение или видеокадры на выбранный угол.',
            'flip':'Отразить кадр по горизонтали или вертикали.',
            'fps':'Кадров в секунду в выходном видео или GIF. 0 сохраняет исходную частоту (для GIF по умолчанию 15).',
            'speed':'Скорость воспроизведения: 1× без изменений, 2× вдвое быстрее.',
            'codec':'Способ кодирования выходного видео. auto выбирает кодек по формату.',
            'hardware':'CPU работает на любом компьютере; GPU использует аппаратный кодировщик при его наличии.',
            'target_mb':'Приблизительный предельный размер результата в мегабайтах. 0 означает без лимита.',
            'audio_bitrate':'Битрейт выходного звука в килобитах в секунду: больше значит качественнее и крупнее файл.',
            'sample_rate':'Частота дискретизации выходного звука в герцах. 0 означает оставить частоту исходного файла.',
            'channels':'Количество звуковых каналов: 1 — моно, 2 — стерео, 0 — как в исходном файле.',
            'normalize':'Выравнивает воспринимаемую громкость аудио.',
            'volume':'1× оставляет громкость, 0.5× делает тише, 2× громче.',
            'strip_metadata':'Убрать служебные теги и данные камеры, если этот формат поддерживает удаление.',
            'frame_ms':'Сколько миллисекунд показывать каждый кадр GIF.',
            'frame_delays':'Длительности отдельных кадров GIF через запятую, например 100,200,100.',
            'loop':'Число повторов GIF. 0 означает бесконечное повторение.',
            'emoji_frames':'Сколько кадров уместить на квадратный лист 1024×1024 для Animated Emoji VRChat: 4, 16 или 64. Большее число даёт плавнее движение и меньший размер каждого кадра.',
            'pages':'Номера страниц PDF в нужном порядке, например 1,3,5-8. Пустое поле означает все страницы.'}
        for key,w in self.controls.items():
            w.setToolTip(help_text[key]);self.advanced_form.labelForField(w).setToolTip(help_text[key])
        self.quality.setToolTip('Качество сжатия для изображений или перекодированного видео.')
        self.resolution.setToolTip('Готовый размер результата. «Оригинальное» использует значения из дополнительных настроек.')
    def update_visible_options(self, *_):
        if not hasattr(self,'advanced_form') or not hasattr(self,'extra_row'): return
        op=self.operation.currentData(); fmt=self.format.currentText()
        image={'width','height','scale_mode','no_upscale','crop','rotate','flip','strip_metadata','target_mb'}
        video={'width','height','scale_mode','no_upscale','start','end','crop','rotate','flip','fps','speed','codec','hardware','target_mb','audio_bitrate','sample_rate','channels','normalize','volume','strip_metadata'}
        audio={'start','end','speed','audio_bitrate','sample_rate','channels','normalize','volume','strip_metadata'}
        visible={
            'image':image, 'images_pdf':image-{'strip_metadata','target_mb'},
            'images_gif':image-{'strip_metadata','target_mb'}|{'frame_ms','frame_delays','loop'},
            'video':video, 'burn_subtitle':video,
            'video_gif':video-{'codec','hardware','target_mb','audio_bitrate','sample_rate','channels','normalize','volume','strip_metadata'}|{'loop'},
            'emoji':{'start','end','crop','rotate','flip','emoji_frames'},
            'audio':audio, 'merge_audio':audio-{'start','end'},
            'replace_audio':{'start','end','audio_bitrate','strip_metadata'},
            'pdf_pages':{'pages','rotate','strip_metadata'}, 'pdf_compress':{'strip_metadata'},
            'remux':{'start','end','strip_metadata'}, 'merge_video':{'strip_metadata'},
            'mute':{'start','end','strip_metadata'},'add_subtitle':{'start','end','strip_metadata'},
            'remove_subtitle':{'start','end','strip_metadata'},'extract_subtitle':{'start','end'},
        }.get(op,set())
        self._visible_options=visible
        for key,w in self.controls.items():
            w.setVisible(key in visible); self.advanced_form.labelForField(w).setVisible(key in visible)
        self.advanced.setVisible(bool(visible))
        self.lock_ratio.setVisible('width' in visible and 'height' in visible)
        self.size_row.setVisible('target_mb' in visible)
        self.update_size_hint()
        quality_visible=op in ('image','video','burn_subtitle') and fmt not in ('png','bmp','tiff','ico')
        self.quality.setVisible(quality_visible);self.basic_form.labelForField(self.quality).setVisible(quality_visible)
        resolution_visible=op in ('image','video','burn_subtitle','images_gif','images_pdf','video_gif')
        self.resolution.setVisible(resolution_visible);self.basic_form.labelForField(self.resolution).setVisible(resolution_visible)
    def reset_options(self):
        self._preset_active=False;self._format_pinned=False;self.apply_options(asdict(Options(format=self.format.currentText())))
        self.update_source(force=True)
    def dimension_changed(self,changed,value):
        if self._syncing_dimensions:return
        if self.resolution.currentIndex():
            self.resolution.blockSignals(True);self.resolution.setCurrentIndex(0);self.resolution.blockSignals(False)
        if not self.lock_ratio.isChecked() or not self._source_ratio or not value:return
        other='height' if changed=='width' else 'width'
        desired=round(value/self._source_ratio if changed=='width' else value*self._source_ratio)
        self._syncing_dimensions=True
        try:self.controls[other].setValue(min(16384,max(1,desired)))
        finally:self._syncing_dimensions=False
    def choose_resolution(self,index):
        if not index or not hasattr(self,'controls') or 'width' not in self.controls:return
        width,height=map(int,self.resolution.itemText(index).split(' × '))
        if self._source_ratio and abs(width/height-self._source_ratio)>.005:self.lock_ratio.setChecked(False)
        self._syncing_dimensions=True
        try:self.controls['width'].setValue(width);self.controls['height'].setValue(height)
        finally:self._syncing_dimensions=False
    def size_slider_changed(self,percent):
        if self._syncing_size:return
        self._syncing_size=True
        try:
            value=round(self._source_bytes*percent/100/1048576,6) if percent<100 and self._source_bytes else 0
            if value and self.operation.currentData() in ('video','burn_subtitle') and self._source_duration and self._source_has_audio:
                total_rate=value*1048576*8*.95/self._source_duration
                self.controls['audio_bitrate'].setValue(max(8,min(192,int(total_rate*.2/1000))))
            self.controls['target_mb'].setValue(max(.000001,value) if value else 0)
        finally:self._syncing_size=False
        self.update_size_hint()
    def target_size_changed(self,value):
        if self._syncing_size:return
        self._syncing_size=True
        try:self.size_slider.setValue(max(5,min(100,round(value*1048576/self._source_bytes*100))) if value and self._source_bytes else 100)
        finally:self._syncing_size=False
        self.update_size_hint()
    def update_size_hint(self):
        value=self.controls['target_mb'].value()
        self.size_percent.setText(f'{self.size_slider.value()}%' if value else 'Без ограничения')
        if not self._source_bytes:
            self.size_hint.setText('Добавьте файл, чтобы выбрать размер результата.');return
        if not value:
            self.size_hint.setText(f'Исходник {size(self._source_bytes)} · без лимита размера');return
        hint=f'Исходник {size(self._source_bytes)} → цель до {size(value*1048576)}'
        if self.operation.currentData() in ('video','burn_subtitle') and self._source_duration:
            rate=value*1048576*8*.95/self._source_duration-(self.controls['audio_bitrate'].value()*1000 if self._source_has_audio else 0)
            hint+=f' · видеобитрейт ≈ {max(0,round(rate/1000))} кбит/с'
            if rate<32000:hint+=' · цель слишком мала для этой длительности'
        elif self.operation.currentData()=='image' and self.format.currentText() not in ('jpg','webp','avif'):
            hint+=' · для этого формата может уменьшиться разрешение'
        self.size_hint.setText(hint)
    def options(self):
        o=Options(format=self.format.currentText(),quality=[82,95,55][self.quality.currentIndex()],extra_file=self.extra_file.text())
        for k,w in self.controls.items():
            if k not in self._visible_options: continue
            val=w.isChecked() if isinstance(w,QCheckBox) else w.value() if isinstance(w,(QSpinBox,QDoubleSpinBox)) else w.currentText() if isinstance(w,QComboBox) else w.text()
            if k in ('rotate','emoji_frames'): val=int(val)
            setattr(o,k,val)
        o.validate(); return o
    def apply_options(self,data):
        self.resolution.setCurrentIndex(0)
        self.format.setCurrentText(data.get('format',self.format.currentText()))
        self.quality.setCurrentIndex(1 if data.get('quality',82)>90 else 2 if data.get('quality',82)<65 else 0)
        self._syncing_dimensions=True
        for k,w in self.controls.items():
            if k not in data: continue
            v=data[k]
            if isinstance(w,QCheckBox): w.setChecked(v)
            elif isinstance(w,(QSpinBox,QDoubleSpinBox)): w.setValue(v)
            elif isinstance(w,QComboBox): w.setCurrentText(str(v))
            else: w.setText(str(v))
        self._syncing_dimensions=False
    def choose_files(self):
        dialog=self.files_dialog()
        if dialog.exec()==QDialog.DialogCode.Accepted:self.add_paths(dialog.selectedFiles())
    def files_dialog(self):
        dialog=QFileDialog(self,'Добавить файлы')
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog,True)
        dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        dialog.setNameFilter(self.section_file_filter())
        return dialog
    def section_file_filter(self):
        extensions={'Видео':'*.mp4 *.mkv *.mov *.avi *.webm *.wmv *.m4v *.mpeg *.mpg *.ts *.mts *.flv *.3gp *.ogv',
                    'Аудио':'*.mp3 *.wav *.flac *.aac *.m4a *.ogg *.opus *.wma *.aiff *.ac3 *.mp4 *.mkv *.mov',
                    'Изображения':'*.png *.jpg *.jpeg *.webp *.avif *.bmp *.gif *.tiff *.ico *.heic *.heif',
                    'Документы':'*.doc *.docx *.odt *.rtf *.txt *.html *.htm *.xls *.xlsx *.ods *.ppt *.pptx *.odp',
                    'PDF':'*.pdf *.png *.jpg *.jpeg *.webp *.bmp *.tiff',
                    'Электронные книги':'*.epub *.mobi *.azw3 *.htmlz',
                    'VRChat':'*.gif *.mp4 *.mkv *.mov'}
        return ('Подходящие файлы ('+extensions[self._section_filter]+')') if self._section_filter in extensions else 'Все файлы (*)'
    def choose_folder(self):
        dialog=self.folder_dialog()
        if dialog.exec()==QDialog.DialogCode.Accepted:self.add_paths(dialog.selectedFiles())
    def folder_dialog(self):
        dialog=QFileDialog(self,'Добавить папку')
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog,True)
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly,True)
        return dialog
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
        expected=SECTION_KINDS.get(self._section_filter)
        if expected is not None:
            accepted=[];rejected=[];current=self.input_paths()
            for p in result:
                candidates=compatible_operations(current+accepted+[p])
                valid=any(op.category==self._section_filter for op in candidates)
                if (file_kind(p) not in expected or not valid or
                    (self._section_filter=='VRChat' and file_kind(p)=='image' and Path(p).suffix.lower()!='.gif')):
                    rejected.append(p)
                else:accepted.append(p)
            result=accepted
            if rejected:self.toast(f'Не подходят для раздела «{self._section_filter}»: {len(rejected)} файл(ов).')
        if not result:return
        existing={self.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.files.count())}
        for p in result:
            if p not in existing:
                item=QListWidgetItem(Path(p).name); item.setToolTip(p); item.setData(Qt.ItemDataRole.UserRole,p); self.files.addItem(item)
        self.refresh_compatible()
        if self.files.count() and not self.files.currentItem():self.files.setCurrentRow(0);self.files.clearSelection()
        elif self.files.currentItem():self.update_source(force=True)
        self.show_page(self.editor); self.heading.setText('Подготовка файлов')
        if result:self.toast(f'Добавлено: {len(result)}. Подходящие действия выбраны автоматически.')
    def input_paths(self): return [self.files.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.files.count())]
    def remove_inputs(self):
        for item in self.files.selectedItems(): self.files.takeItem(self.files.row(item))
        self.refresh_compatible()
        self.update_source(force=True)
    def update_source(self,force=False):
        if not hasattr(self,'media_preview'):return
        item=self.files.currentItem()
        path=item.data(Qt.ItemDataRole.UserRole) if item else (self.input_paths()[0] if self.input_paths() else None)
        if not force and path==getattr(self,'_source_path',None):return
        self._source_path=path;self._source_token+=1;token=self._source_token
        self.media_preview.set_file(path)
        self._source_bytes=0;self._source_duration=0;self._source_has_audio=False
        self.size_slider.setEnabled(False);self.update_size_hint()
        if not path:
            return
        self.media_preview.details.setText('Читаю параметры файла…')
        def done(info):
            if token!=self._source_token:return
            if isinstance(info,Exception):
                self.media_preview.details.setText(f'{Path(path).name} • параметры недоступны: {info}');return
            bits=[Path(path).name,size(info['bytes'])]
            if info.get('width'):bits.append(f"{info['width']} × {info['height']}")
            if info.get('frames',1)>1:bits.append(f"{info['frames']} кадр(ов)")
            if info.get('duration'):bits.append(f"{info['duration']:.1f} с")
            if info.get('fps'):bits.append(f"{info['fps']:g} FPS")
            if info.get('sample_rate'):bits.append(f"{info['sample_rate']} Гц")
            if info.get('channels'):bits.append(f"{info['channels']} канал(а)")
            if info.get('pages'):bits.append(f"{info['pages']} стр.")
            self.media_preview.details.setText('  •  '.join(bits))
            self._source_bytes=info['bytes'];self._source_duration=info.get('duration',0);self._source_has_audio=info.get('has_audio',False)
            self.size_slider.setEnabled(bool(self._source_bytes));self.update_size_hint()
            if info.get('width') and info.get('height'):
                self._source_ratio=info['width']/info['height']
            else:self._source_ratio=None
            if not self._preset_active:
                self._syncing_dimensions=True
                for key in ('width','height','fps','sample_rate','channels','frame_ms'):
                    if info.get(key) is not None and key in self.controls:
                        self.controls[key].setValue(info[key])
                self._syncing_dimensions=False
            self.preview_timer.start(180)
        self.async_.run(lambda:source_info(path),done)
    def refresh_live_preview(self):
        path=getattr(self,'_source_path',None)
        if not path:return
        if file_kind(path)=='image':self.refresh_image_preview()
        elif file_kind(path)=='video' and self.operation.currentData() in ('video','burn_subtitle','video_gif'):
            self.compare_video_frame()
    def refresh_image_preview(self):
        path=getattr(self,'_source_path',None)
        if not path or file_kind(path)!='image' or Path(path).suffix.lower()=='.gif':return
        if self.operation.currentData() not in ('image','images_pdf','images_gif'):
            self.media_preview.show_pixmap(QPixmap(path));return
        try:
            from PIL import Image, ImageOps
            from io import BytesIO
            with Image.open(path) as source:
                image=ImageOps.exif_transpose(source).convert('RGBA')
                crop=self.controls['crop'].text().strip()
                if crop:
                    x,y,w,h=[int(v.strip()) for v in crop.split(',')]
                    if w>0 and h>0:image=image.crop((x,y,x+w,y+h))
                angle=int(self.controls['rotate'].currentText())
                if angle:image=image.rotate(-angle,expand=True)
                flip=self.controls['flip'].currentText()
                if flip=='horizontal':image=ImageOps.mirror(image)
                elif flip=='vertical':image=ImageOps.flip(image)
                width=self.controls['width'].value();height=self.controls['height'].value()
                if width or height:
                    width=width or round(image.width*height/image.height)
                    height=height or round(image.height*width/image.width)
                    if self.controls['no_upscale'].isChecked():width=min(width,image.width);height=min(height,image.height)
                    mode=self.controls['scale_mode'].currentText()
                    if mode=='fit':image.thumbnail((width,height))
                    elif mode=='fill':image=ImageOps.fit(image,(width,height))
                    else:image=image.resize((width,height))
                image.thumbnail((1100,700)); data=BytesIO();image.save(data,'PNG')
            pix=QPixmap();pix.loadFromData(data.getvalue());self.media_preview.show_pixmap(pix)
        except (ValueError,OSError,ZeroDivisionError):pass # Keep the last valid frame while the crop field is being typed.
    def compare_video_frame(self):
        path=getattr(self,'_source_path',None)
        if not path or file_kind(path)!='video':return
        try:o=self.options()
        except Exception as error:self.error(error);return
        position=self.media_preview.player.position()/1000 if self.media_preview.player else 0
        position=max(position,o.start)
        if o.end:position=min(position,max(o.start,o.end-.1))
        self._preview_token+=1;token=self._preview_token
        self.compare_video_button.setEnabled(False)
        def prepare():
            from tempfile import TemporaryDirectory
            ff=executable('ffmpeg')
            if not ff:raise RuntimeError('Нужен FFmpeg.')
            with TemporaryDirectory() as folder:
                before=Path(folder)/'before.png';after=Path(folder)/'after.png'
                vf,_=Engine().filters(o)
                vf=[part for part in vf if not part.startswith(('fps=','setpts='))]
                for target,filters in ((before,[]),(after,vf)):
                    command=[ff,'-v','error','-ss',str(position),'-i',path,'-frames:v','1']
                    if filters:command+=['-vf',','.join(filters)]
                    command+=['-y',str(target)]
                    Engine().runner.run(command)
                return before.read_bytes(),after.read_bytes()
        def show(result):
            self.compare_video_button.setEnabled(True)
            if token!=self._preview_token or path!=getattr(self,'_source_path',None):return
            if isinstance(result,Exception):self.error(result);return
            before=QPixmap();after=QPixmap();before.loadFromData(result[0]);after.loadFromData(result[1])
            self.media_preview.show_video_comparison(before,after)
        self.async_.run(prepare,show)
    def refresh_compatible(self):
        paths=self.input_paths();compatible=compatible_operations(paths)
        signature=tuple(sorted({file_kind(path) for path in paths}))
        previous_signature=getattr(self,'_detected_signature',None)
        requested=getattr(self,'_requested_operation',None)
        section=self._section_filter if self._section_filter in SECTION_KINDS else None
        allowed=[op for op in compatible if op.category==section] if section else compatible
        if not allowed:allowed=compatible
        preferred=requested if requested in {op.id for op in allowed} else self.operation.currentData() if signature==getattr(self,'_detected_signature',None) else allowed[0].id
        self._detected_signature=signature
        if preferred not in {op.id for op in allowed}:preferred=allowed[0].id
        if paths and section is None:
            section=REGISTRY[preferred].category
            allowed=[op for op in compatible if op.category==section]
        self.operation.blockSignals(True);self.operation.clear()
        for op in allowed:self.operation.addItem(icon_for(op.category),op.label,op.id)
        self.operation.setCurrentIndex(self.operation.findData(preferred));self.operation.blockSignals(False)
        if paths:
            kinds={category(path) for path in paths}
            desc=next(iter(kinds)) if len(kinds)==1 else 'Смешанные типы'
            self.input_summary.setText(f'{len(paths)} файл(ов) • {desc} • доступно действий: {len(allowed)}')
        else:self.input_summary.setText('Добавь файлы — покажу доступные действия.')
        count=1 if REGISTRY[preferred].multiple else len(paths)
        self.enqueue_button.setText(f'Добавить в очередь: {count} задач(и)   Ctrl+Enter' if paths else 'Добавить в очередь   Ctrl+Enter')
        if paths:
            self.select_section(REGISTRY[preferred].category)
            self._section_filter=REGISTRY[preferred].category
            self.current=REGISTRY[preferred].category
        self.operation_changed()
        if paths and signature!=previous_signature and not self._format_pinned and preferred in ('image','video','audio'):
            source_format=Path(paths[0]).suffix.lower().lstrip('.')
            source_format={'jpeg':'jpg'}.get(source_format,source_format)
            if self.format.findText(source_format)>=0:self.format.setCurrentText(source_format)
        self.rebuild_tools(self.search.text())
    def choose_extra(self):
        p,_=QFileDialog.getOpenFileName(self,'Выбрать дорожку')
        if p:self.extra_file.setText(p)
    def choose_output(self):
        p=QFileDialog.getExistingDirectory(self,'Папка результата',self.output.text())
        if p:self.output.setText(p);self.store.set('output',p)
    def enqueue(self,immediate=False):
        try:
            paths=self.input_paths()
            if not paths: self.choose_files(); return
            o=self.options(); op=REGISTRY[self.operation.currentData()]
            if op.id not in {candidate.id for candidate in compatible_operations(paths)}:
                raise ValueError('Выбранное действие не подходит для загруженных файлов.')
            if op.backend in ('ffmpeg','soffice','ebook-convert') and not executable(op.backend): raise ValueError('Нужный компонент не установлен. Откройте Настройки → Компоненты.')
            if not self.output.text().strip(): raise ValueError('Выберите папку результата.')
            jobs=[Job(paths if op.multiple else [p],op.id,asdict(o),self.output.text()) for p in (paths[:1] if op.multiple else paths)]
            if immediate:self._immediate_ids.update(j.id for j in jobs)
            self.queue.add(jobs)
            if immediate:self.toast(f'Обработка началась: {len(jobs)} задач(и). Результат появится здесь после завершения.')
            else:self.navigate('Очередь')
        except Exception as e:self.error(e)
    def convert_now(self):self.enqueue(immediate=True)
    def set_operation(self,id):
        index=self.operation.findData(id)
        if index<0 and id in {op.id for op in compatible_operations(self.input_paths())}:
            self._section_filter=REGISTRY[id].category;self.refresh_compatible()
            index=self.operation.findData(id)
        if index<0:
            self.toast('Это действие не подходит для загруженных файлов. Удалите их или выберите доступное действие.');return
        self._requested_operation=id;self._section_filter=REGISTRY[id].category;self.current=REGISTRY[id].category
        self.operation.setCurrentIndex(index);self.show_page(self.editor);self.heading.setText(REGISTRY[id].category)
        self.select_section(REGISTRY[id].category)
    def select_section(self,name):
        for row in range(self.nav.count()):
            if self.nav.item(row).text()==name:
                old=self.nav.blockSignals(True);self.nav.setCurrentRow(row);self.nav.blockSignals(old);break
    def show_page(self,page):
        if self.pages.currentWidget() is page:return
        if getattr(self,'page_anim',None):self.page_anim.stop()
        if getattr(self,'animated_page',None):self.animated_page.setGraphicsEffect(None)
        self.pages.setCurrentWidget(page)
        if not self.store.get('animations',True):return
        effect=QGraphicsOpacityEffect(page);page.setGraphicsEffect(effect);effect.setOpacity(.72)
        self.animated_page=page
        self.page_anim=QPropertyAnimation(effect,b'opacity',self);self.page_anim.setDuration(190)
        self.page_anim.setStartValue(.72);self.page_anim.setEndValue(1.0)
        self.page_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.page_anim.finished.connect(lambda:page.setGraphicsEffect(None));self.page_anim.start()
    def navigate(self,name):
        if not name:return
        self.current=name; self.heading.setText('Начнём с файла' if name=='Главная' else name)
        if name=='Главная':
            self._section_filter=None;self._requested_operation=None;self._format_pinned=False;self._preset_active=False
            self.show_page(self.home)
        elif name=='Очередь': self.show_page(self.queue_page); self.refresh_queue();self.refresh_result_preview()
        elif name=='История': self.show_page(self.history_page); self.refresh_queue();self.refresh_result_preview()
        elif name=='Избранное': self.show_presets()
        elif name=='Настройки': self.show_settings()
        elif name=='О программе': self.show_about()
        else:
            if name in SECTION_KINDS:
                self._section_filter=name
                paths=self.input_paths();expected=SECTION_KINDS[name]
                if paths and expected is not None and not any(o.category==name for o in compatible_operations(paths)):
                    self.files.clear();self._source_path=None;self.media_preview.set_file(None)
                    self.toast('Список входных файлов очищен для нового раздела. Исходные файлы не удалены.')
                self.refresh_compatible();self._section_filter=name
            op=next((o for o in compatible_operations(self.input_paths()) if o.category==name),None)
            if op:self.set_operation(op.id)
            elif self.input_paths():
                self.current=REGISTRY[self.operation.currentData()].category
                self.select_section(self.current);self.show_page(self.editor)
                self.heading.setText('Подготовка файлов')
                self.toast('Для загруженных файлов в этом разделе нет подходящих действий.')
            else:
                op=next((o for o in OPERATIONS if o.category==name),None)
                if op:self.set_operation(op.id)
    def rebuild_tools(self,query=''):
        while self.tools_grid.count():
            item=self.tools_grid.takeAt(0)
            if item.widget():item.widget().deleteLater()
        featured=('video','remux','audio','image','images_gif','video_gif','emoji','images_pdf','pdf_merge','archive','document','ebook')
        allowed={op.id for op in compatible_operations(self.input_paths())}
        ops=[o for o in OPERATIONS if o.id in allowed and (query.lower() in (o.label+' '+o.category).lower() if query else o.id in featured)]
        for i,op in enumerate(ops):
            b=button(op.label,lambda id=op.id:self.set_operation(id));b.setIcon(icon_for(op.category));b.setIconSize(QSize(25,25))
            b.setMinimumHeight(62); self.tools_grid.addWidget(b,i//2,i%2)
    def filter_tools(self,text):
        self.show_page(self.home); self.heading.setText('Инструменты'); self.rebuild_tools(text)
    def clear_extra(self):
        while self.extra_layout.count():
            item=self.extra_layout.takeAt(0)
            if item.widget():item.widget().hide();item.widget().deleteLater()
            if item.layout():
                while item.layout().count():
                    child=item.layout().takeAt(0)
                    if child.widget():child.widget().hide();child.widget().deleteLater()
                item.layout().deleteLater()
        self.show_page(self.extra)
    def selected_jobs(self):
        listing=self.history_list if self.current=='История' else self.queue_list
        ids={i.data(Qt.ItemDataRole.UserRole) for i in listing.selectedItems()}
        if not ids and listing.currentItem():ids={listing.currentItem().data(Qt.ItemDataRole.UserRole)}
        return [j for j in self.queue.jobs if j.id in ids]
    def refresh_queue(self):
        jobs=list(self.queue.jobs)
        signature=tuple((j.id,j.status,round(j.progress,2),j.output,j.after) for j in jobs)
        if signature!=getattr(self,'_queue_signature',None):
            self._queue_signature=signature
            for listing,shown in ((self.queue_list,[j for j in jobs if j.status!='done']+[j for j in jobs if j.status=='done'][-3:]),
                                  (self.history_list,[j for j in reversed(jobs) if j.status=='done'])):
                selected={i.data(Qt.ItemDataRole.UserRole) for i in listing.selectedItems()}
                current=listing.currentItem().data(Qt.ItemDataRole.UserRole) if listing.currentItem() else None
                scroll=listing.verticalScrollBar().value();listing.blockSignals(True);listing.clear()
                for j in shown:
                    text=f'{STATUS[j.status]}'+(f'   {int(j.progress*100)}%' if j.status=='running' else '')+f'    {Path(j.inputs[0]).name}\n{REGISTRY[j.operation].label}'
                    if j.status=='done':
                        change=(1-j.after/j.before)*100 if j.before else 0
                        text+=f'   •   {size(j.before)} → {size(j.after)}   ({change:+.1f}% экономии)   •   {j.elapsed:.1f} с'
                    elif j.status=='failed':text+='   •   '+j.error.splitlines()[-1][:140]
                    item=QListWidgetItem(icon_for(REGISTRY[j.operation].category),text)
                    item.setData(Qt.ItemDataRole.UserRole,j.id)
                    item.setData(Qt.ItemDataRole.UserRole+1,j.output if j.status=='done' else '')
                    listing.addItem(item);item.setSelected(j.id in selected)
                    if j.id==current:listing.setCurrentItem(item)
                if listing.count() and not listing.currentItem():listing.setCurrentRow(0)
                listing.verticalScrollBar().setValue(scroll);listing.blockSignals(False)
            finished=[j for j in jobs if j.status=='done']
            saved=sum(j.before-j.after for j in finished)
            self.history_summary.setText(f'{len(finished)} готово  ·  {"сэкономлено " + size(saved) if saved>=0 else "размер увеличился на " + size(-saved)}  ·  дважды щёлкните результат для открытия' if finished else 'Пока нет готовых результатов.')
            self.refresh_result_preview()
        active=[j for j in jobs if j.status in ('waiting','running')]; complete=sum(j.status=='done' for j in jobs)
        pct=round(sum(j.progress if j.status=='running' else 1 if j.status=='done' else 0 for j in jobs)/max(len(jobs),1)*100)
        self.progress.setValue(pct); self.progress.setFormat(f'{complete} / {len(jobs)} готовы  •  {pct}%')
        self.setWindowTitle((f'{pct}% — ' if active else '')+'COKKER Converter')
        if hasattr(self,'tray'):self.tray.setToolTip(f'COKKER Converter\n{len(active)} задач • {pct}%' if active else 'COKKER Converter — готов к работе')
    def refresh_result_preview(self):
        listing=self.history_list if self.current=='История' else self.queue_list
        preview,mode=(self.history_preview,self.history_preview_mode) if self.current=='История' else (self.queue_preview,self.queue_preview_mode)
        item=listing.currentItem()
        job=next((j for j in self.queue.jobs if item and j.id==item.data(Qt.ItemDataRole.UserRole)),None)
        if not job:preview.set_file(None);mode.hide();return
        before=job.inputs[0];after=job.output if job.status=='done' and Path(job.output).is_file() else None
        kind=file_kind(before)
        comparison=bool(after and kind=='image' and Path(before).suffix.lower()!='.gif' and file_kind(after)=='image' and Path(after).suffix.lower()!='.gif')
        mode.setVisible(bool(after and not comparison))
        if comparison:
            if preview.path!=before:preview.set_file(before)
            preview.show_pixmap(QPixmap(after))
        else:preview.set_file(after if after and mode.currentIndex()==1 else before)
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
        if id in self._immediate_ids:
            self._immediate_ids.discard(id)
            if j and j.status=='done':
                self.navigate('История')
                for i in range(self.history_list.count()):
                    if self.history_list.item(i).data(Qt.ItemDataRole.UserRole)==id:
                        self.history_list.setCurrentRow(i);self.refresh_result_preview();break
                self.toast('Результат готов — откройте его здесь или сравните с исходником.')
            elif j:self.toast(f'Обработка не завершена: {j.error}')
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
    def use_quick(self,operation,fmt,width=0,height=0):
        self._requested_operation=operation;self.set_operation(operation)
        self.apply_options(asdict(Options(format=fmt,width=width,height=height)))
        self._preset_active=bool(width or height);self._format_pinned=True
        if not self._preset_active and self.input_paths():self.update_source(force=True)
        self.toast('Действие готово. Перетащите файл в окно или нажмите «Добавить».')
    def add_favorite(self):
        try:
            op=REGISTRY[self.operation.currentData()]
            data=asdict(self.options());data.pop('extra_file')
            name=f'{op.label} → {data["format"]}'
            if data['width'] and data['height']:name+=f' • {data["width"]} × {data["height"]}'
            items=self.presets.all();items.append({'schemaVersion':1,'presetName':name,'category':op.category,'operation':op.id,'parameters':data})
            self.presets.save(items);self.toast('Добавлено в Избранное. Выберите действие там одним кликом.')
        except Exception as e:self.error(e)
    def show_presets(self):
        self.clear_extra(); self.extra_layout.addWidget(label('Нажмите на действие, затем перетащите файл в окно. Свои настройки добавляйте кнопкой ★ в редакторе.','subtitle'))
        quick=QHBoxLayout();quick.addWidget(button('PNG → JPG',lambda:self.use_quick('image','jpg')))
        quick.addWidget(button('Размер 1920 × 1080',lambda:self.use_quick('image','jpg',1920,1080)))
        self.extra_layout.addLayout(quick)
        listing=QListWidget(); listing.setDragDropMode(QListWidget.DragDropMode.InternalMove); listing.setMinimumHeight(300)
        for p in self.presets.all():
            item=QListWidgetItem('★  '+p['presetName']); item.setData(Qt.ItemDataRole.UserRole,p); listing.addItem(item)
        def persist():self.presets.save([listing.item(i).data(Qt.ItemDataRole.UserRole) for i in range(listing.count())])
        listing.model().rowsMoved.connect(lambda *args:persist())
        def use():
            if listing.currentItem():
                p=listing.currentItem().data(Qt.ItemDataRole.UserRole)
                self._requested_operation=p['operation'];self.set_operation(p['operation']);self.apply_options(p['parameters'])
                self._preset_active=True;self._format_pinned=True;self.toast('Пресет готов. Добавьте файлы или нажмите Ctrl+Enter.')
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
        listing.itemClicked.connect(lambda *_:use())
        self.extra_layout.addWidget(listing);row=QWidget();rl=QHBoxLayout(row)
        for text,fn in [('Применить / изменить',use),('Дублировать',duplicate),('Удалить',delete),('Экспорт JSON',export),('Импорт JSON',import_)]:rl.addWidget(button(text,fn))
        self.extra_layout.addWidget(row);self.extra_layout.addStretch()
    def show_settings(self):
        self.clear_extra()
        box,bl=card();bl.addWidget(label('Интерфейс и обработка','title'));form=QFormLayout()
        theme=combo(['system','dark','light']);theme.setCurrentText(self.store.get('theme','dark'));theme.currentTextChanged.connect(lambda v:(self.store.set('theme',v),self.apply_theme()));form.addRow('Тема',theme)
        concurrency=spin(1,4,self.store.get('concurrency',1));concurrency.valueChanged.connect(lambda v:self.store.set('concurrency',v));form.addRow('Параллельные задачи',concurrency)
        bl.addLayout(form)
        for key,text,default in [('animations','Плавные переходы и отклик кнопок',True),('sleep_block','Не давать Windows заснуть во время обработки',True),('clipboard','Ctrl+V: добавлять файлы и изображения',True),('notifications','Уведомления о завершении',True),('close_tray','Закрывать окно в трей',False),('minimize_tray','Сворачивать в трей',False)]:
            w=QCheckBox(text);w.setChecked(self.store.get(key,default));w.toggled.connect(lambda v,k=key:(self.store.set(k,v),QApplication.instance().setProperty('animations',v) if k=='animations' else None));bl.addWidget(w)
        self.extra_layout.addWidget(box)
        box,bl=card();bl.addWidget(label('Запуск с Windows','title'));auto=QCheckBox('Запускать вместе с Windows');tray=QCheckBox('При автозапуске открывать сразу в трее');auto.setChecked(self.store.get('autostart',False));tray.setChecked(self.store.get('autostart_tray',False));tray.setEnabled(auto.isChecked());auto.setEnabled(os.name=='nt')
        def save_startup():
            try:
                startup(auto.isChecked(),tray.isChecked());self.store.set('autostart',auto.isChecked());self.store.set('autostart_tray',tray.isChecked());tray.setEnabled(auto.isChecked())
            except Exception as e:
                auto.blockSignals(True);auto.setChecked(self.store.get('autostart',False));auto.blockSignals(False);self.error(e)
        auto.toggled.connect(save_startup);tray.toggled.connect(save_startup);bl.addWidget(auto);bl.addWidget(tray);self.extra_layout.addWidget(box)
        box,bl=card();bl.addWidget(label('Компоненты','title'))
        bl.addWidget(label('Установка и удаление выполняются отдельно или пакетом. WinGet может запросить подтверждение Windows. Встроенные FFmpeg и ffprobe можно убрать из папки программы; обновление Portable вернёт их.','subtitle'))
        for name,title,package in COMPONENTS:
            p=executable(name);entry=QWidget();entry.setObjectName('componentRow');row=QHBoxLayout(entry);row.setContentsMargins(0,3,0,3)
            details=QVBoxLayout();details.addWidget(label(title+'  ·  '+('установлен' if p else 'не установлен')))
            if p:
                path_label=label(p,'subtitle');path_label.setToolTip(p);details.addWidget(path_label)
            row.addLayout(details,1)
            if os.name=='nt' and (shutil.which('winget') or p and self.is_bundled_component(p)):
                action='remove' if p else 'install'
                control=button('Удалить' if p else 'Установить',lambda n=name:self.manage_components('remove' if executable(n) else 'install',[n]))
                control.setEnabled(self._install_process is None and not self._install_tasks and not self.queue.active)
                row.addWidget(control)
            elif not p:row.addWidget(button('Сайт загрузки',lambda n=name:QDesktopServices.openUrl(QUrl(URLS.get(n,URLS['ffmpeg'])))))
            bl.addWidget(entry)
        bulk=QHBoxLayout();all_install=button('Установить недостающие',lambda:self.manage_components('install'))
        all_remove=button('Удалить установленные',lambda:self.manage_components('remove'))
        all_install.setEnabled(os.name=='nt' and bool(shutil.which('winget')) and not self._install_process and not self._install_tasks and not self.queue.active)
        all_remove.setEnabled(os.name=='nt' and not self._install_process and not self._install_tasks and not self.queue.active)
        bulk.addWidget(all_install);bulk.addWidget(all_remove);bl.addLayout(bulk)
        if not shutil.which('winget') and os.name=='nt':bl.addWidget(label('WinGet не найден. Установите «Установщик приложений» Windows или используйте сайт компонента.','subtitle'))
        if self._install_process or self._install_tasks:
            bl.addWidget(label('Работа с компонентами: '+getattr(self,'_install_name','подготовка'),'subtitle'))
            self.install_progress=QProgressBar();self.install_progress.setRange(0,0);self.install_progress.setFormat('Загрузка и установка…');bl.addWidget(self.install_progress)
            bl.addWidget(button('Отменить установку',self.cancel_install))
        elif getattr(self,'_install_status',''):bl.addWidget(label(self._install_status,'subtitle'))
        if self._install_process or self._install_tasks or self._install_output:
            self.install_log=QPlainTextEdit();self.install_log.setReadOnly(True);self.install_log.setMaximumHeight(115)
            self.install_log.setPlaceholderText('Здесь появится ход установки и сообщение об ошибке.')
            self.install_log.setPlainText(self._install_output)
            if self._install_process or self._install_tasks:bl.addWidget(self.install_log)
            else:bl.addWidget(Section('Подробности установки',self.install_log,lambda:self.store.get('animations',True)))
        self.extra_layout.addWidget(box)
        box,bl=card();bl.addWidget(label('Обновление программы','title'))
        bl.addWidget(label(f'Установлена версия {__version__}.','subtitle'))
        automatic_check=QCheckBox('Проверять новые версии при запуске и каждый час')
        automatic_check.setChecked(self.store.get('update_auto_check',True))
        def change_auto_check(enabled):
            self.store.set('update_auto_check',enabled)
            if enabled:QTimer.singleShot(0,lambda:self.check_update(automatic=True))
        automatic_check.toggled.connect(change_auto_check);bl.addWidget(automatic_check)
        automatic_download=QCheckBox('Автоматически скачивать найденное обновление')
        automatic_download.setChecked(self.store.get('update_auto_download',False))
        automatic_download.setToolTip('Скачанный файл проверяется и ждёт вашей команды «Установить». Программа не закрывается сама.')
        def change_auto_download(enabled):
            self.store.set('update_auto_download',enabled)
            if enabled and self._release:QTimer.singleShot(0,lambda:self.download_update(automatic=True))
        automatic_download.toggled.connect(change_auto_download);bl.addWidget(automatic_download)
        bl.addWidget(label('О новой версии сообщу в окне и через системное уведомление. Установка начинается только по вашему нажатию.','subtitle'))
        bl.addWidget(label(self._update_status,'subtitle'))
        if self._update_busy:
            self.update_bar=QProgressBar();self.update_bar.setRange(0,100);self.update_bar.setValue(self._update_percent)
            bl.addWidget(self.update_bar);bl.addWidget(button('Отменить загрузку',self.cancel_update))
        else:
            bl.addWidget(button('Проверить обновления',self.check_update))
            if self._release:
                if os.name=='nt' and getattr(sys,'frozen',False):
                    ready=self._update_ready_version==self._release.version and self._update_ready and Path(self._update_ready).is_file()
                    if not ready:bl.addWidget(button('Скачать без установки',self.download_update))
                    install=button(f'Установить {self._release.version}' if ready else f'Скачать и установить {self._release.version}',self.start_update,True)
                    install.setEnabled(not bool(self.queue.active));bl.addWidget(install)
                    if self.queue.active:bl.addWidget(label('Дождитесь завершения очереди перед обновлением.','subtitle'))
                else:bl.addWidget(button('Открыть выпуск',lambda:QDesktopServices.openUrl(QUrl(self._release.url))))
        self.extra_layout.addWidget(box)
        self.extra_layout.addWidget(label('Файлы обрабатываются локально. Для поиска и скачивания обновлений используется GitHub.','subtitle'));self.extra_layout.addStretch()
        if not self._update_checked and self.store.get('update_auto_check',True) and os.name=='nt' and os.environ.get('QT_QPA_PLATFORM')!='offscreen':
            QTimer.singleShot(0,lambda:self.check_update(automatic=True))
    def is_bundled_component(self,path):
        base=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent
        return Path(path).resolve().parent==(base/'components').resolve()
    def manage_components(self,action,names=None):
        if self._install_process or self._install_tasks:return
        if self.queue.active:self.toast('Сначала дождитесь завершения конвертации.');return
        if os.name!='nt':self.toast('Управление компонентами доступно в Windows.');return
        names=set(names or [name for name,_,_ in COMPONENTS])
        tasks=[(action,name,title,package) for name,title,package in COMPONENTS if name in names and bool(executable(name))==(action=='remove')]
        if not tasks:self.toast('Все компоненты уже в нужном состоянии.');return
        if action=='remove':
            titles=', '.join(t[2] for t in tasks)
            if QMessageBox.question(self,'Удаление компонентов',f'Удалить: {titles}?\nНекоторые форматы станут недоступны, пока компоненты не установлены снова.')!=QMessageBox.StandardButton.Yes:return
        if any(not (action=='remove' and self.is_bundled_component(executable(name))) for _,name,_,_ in tasks) and not shutil.which('winget'):
            self.toast('Для системных компонентов нужен WinGet.');return
        self._install_tasks=tasks;self._install_output='';self._install_cancelled=False;self._install_status='';self.start_next_component()
    def start_next_component(self):
        if self._install_cancelled:
            self._install_tasks=[];self._install_process=None;self._install_status='Операция с компонентами отменена.'
            if self.current=='Настройки':self.show_settings()
            return
        if not self._install_tasks:
            self._install_status='Работа с компонентами завершена. '+self._install_status
            if self.current=='Настройки':self.show_settings()
            self.toast(self._install_status);return
        action,name,title,package=self._install_tasks.pop(0);self._install_name=title
        path=executable(name)
        if action=='remove' and path and self.is_bundled_component(path):
            try:
                for filename in (('ffmpeg.exe','ffprobe.exe') if name=='ffmpeg' else (Path(path).name,)):
                    (Path(path).parent/filename).unlink(missing_ok=True)
                self._install_status=f'{title}: встроенные файлы удалены.'
                self._install_output+=self._install_status+'\n'
            except OSError as error:self._install_status=f'{title}: не удалось удалить встроенные файлы: {error}'
            self.start_next_component();return
        process=QProcess(self);self._install_process=process
        process.setProgram(shutil.which('winget'))
        args=['uninstall' if action=='remove' else 'install','--id',package,'--exact','--source','winget','--accept-source-agreements','--disable-interactivity']
        if action=='install':args+=['--accept-package-agreements']
        process.setArguments(args);process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._install_output+=f'\n{title}: {"установка" if action=="install" else "удаление"}…\n'
        def collect():
            data=bytes(process.readAllStandardOutput()).decode('utf-8','replace')
            if data:
                self._install_output=(self._install_output+data.replace('\r','\n'))[-6000:]
                if self.current=='Настройки' and hasattr(self,'install_log'):
                    self.install_log.setPlainText(self._install_output)
                    bar=self.install_log.verticalScrollBar();bar.setValue(bar.maximum())
        process.readyReadStandardOutput.connect(collect)
        def finish(code,status):
            if self._install_process is not process:return
            collect();self._install_process=None;process.deleteLater()
            if self._install_cancelled:self._install_status=f'{title}: операция отменена.'
            elif code==0:self._install_status=f'{title}: команда завершена. '+('Проверьте статус после перезапуска Windows.' if action=='install' and not executable(name) else '')
            else:
                detail=self._install_output.strip().splitlines()
                self._install_status=f'{title}: ошибка {code}. '+(detail[-1][:160] if detail else process.errorString())
            self._install_output+='\n'+self._install_status+'\n'
            self.start_next_component()
        process.finished.connect(finish)
        process.errorOccurred.connect(lambda error:finish(-1,None) if error==QProcess.ProcessError.FailedToStart else None)
        process.start()
        if self.current=='Настройки':self.show_settings()
    def cancel_install(self):
        self._install_tasks=[]
        process=self._install_process
        self._install_cancelled=True
        if not process:
            self._install_status='Операция отменена.';self.show_settings();return
        if os.name=='nt' and process.processId():
            subprocess.Popen(['taskkill','/PID',str(process.processId()),'/T','/F'],creationflags=subprocess.CREATE_NO_WINDOW)
        else:process.kill()
        self._install_status='Отмена операции…'
    def show_about(self):
        self.clear_extra();box,body=card();body.addWidget(label('COKKER Converter  '+__version__,'title'))
        body.addWidget(label('Локальная обработка видео, аудио, изображений и документов. Предварительная версия: проверяйте результат перед удалением исходников.','subtitle'))
        body.addWidget(label('Все преобразования выполняются на вашем компьютере. Обновления проверяются через GitHub.','subtitle'))
        self.extra_layout.addWidget(box)
        links,layout=card();layout.addWidget(label('Ссылки','title'))
        layout.addWidget(button('Исходный код и выпуски на GitHub',lambda:QDesktopServices.openUrl(QUrl(REPO))))
        layout.addWidget(button('VRChat: сайт для загрузки Emoji',lambda:QDesktopServices.openUrl(QUrl('https://vrchat.com/home'))))
        self.extra_layout.addWidget(links);self.extra_layout.addStretch()
    def apply_theme(self):
        theme=self.store.get('theme','dark')
        if theme=='system':theme='dark' if QApplication.styleHints().colorScheme()==Qt.ColorScheme.Dark else 'light'
        QApplication.instance().setStyleSheet(stylesheet(theme))
    def refresh_update_badge(self):
        if self._release:
            ready=self._update_ready_version==self._release.version and self._update_ready and Path(self._update_ready).is_file()
            self.update_badge.setText(('Установить ' if ready else 'Доступна ') + self._release.version)
            self.update_badge.show()
        else:self.update_badge.hide()
    def check_update(self,automatic=False):
        if self._update_busy or self._update_checking:return
        self._update_checked=True;self._update_checking=True;self._update_status='Проверяю выпуски GitHub…'
        if self.current=='Настройки':self.show_settings()
        def done(value):
            self._update_checking=False
            if isinstance(value,Exception):self._update_status='Не удалось проверить обновления: '+str(value).splitlines()[-1][:180]
            else:
                self._release=value
                self._update_status=f'Доступно обновление {value.version}.' if value else 'Установлена последняя опубликованная версия.'
                self.refresh_update_badge()
                if value and automatic and self.store.get('update_notified_version')!=value.version:
                    self.store.set('update_notified_version',value.version)
                    self.toast(f'Доступна новая версия {value.version}. Откройте настройки для обновления.')
                    if self.store.get('notifications',True) and self.tray.isVisible():
                        self.tray.showMessage('COKKER Converter',f'Доступна версия {value.version}. Установить её можно в настройках.')
                if value and self.store.get('update_auto_download',False) and os.name=='nt' and getattr(sys,'frozen',False):
                    QTimer.singleShot(0,lambda:self.download_update(automatic=True))
            if self.current=='Настройки':self.show_settings()
        self.async_.run(lambda:check_release(__version__),done)
    def on_update_progress(self,percent):
        self._update_percent=percent
        if self.current=='Настройки' and self._update_busy and hasattr(self,'update_bar'):
            self.update_bar.setValue(percent)
    def cancel_update(self):
        self._update_cancel.set();self._update_status='Останавливаю загрузку…'
        if self.current=='Настройки':self.show_settings()
    def download_update(self,automatic=False,install_after=False):
        if not self._release or self._update_busy:return
        if os.name!='nt' or not getattr(sys,'frozen',False):
            if not automatic:QDesktopServices.openUrl(QUrl(self._release.url))
            return
        portable=(Path(sys.executable).parent/'portable.flag').exists()
        kind='portable' if portable else 'setup';release=self._release
        if self._update_ready_version==release.version and self._update_ready_kind==kind and self._update_ready and Path(self._update_ready).is_file():
            if install_after:self._install_ready_update()
            return
        self._update_cancel.clear();self._update_busy=True;self._update_percent=0
        self._update_status=f'Загружаю {release.version} и проверяю файл…'
        if self.current=='Настройки':self.show_settings()
        def work():
            folder=self.store.root/'updates'/release.version
            downloaded=download(release,kind,folder,self.update_progress.emit,self._update_cancel)
            if self._update_cancel.is_set():raise InterruptedError('Загрузка отменена.')
            return downloaded
        def ready(result):
            self._update_busy=False
            if isinstance(result,Exception):
                self._update_status='Загрузка не завершена: '+str(result)
                if self.current=='Настройки':self.show_settings()
                return
            self._update_ready=result;self._update_ready_version=release.version;self._update_ready_kind=kind
            self._update_status=f'Версия {release.version} скачана и проверена. Установите её, когда будете готовы.'
            self.refresh_update_badge()
            if install_after:
                self._install_ready_update();return
            self.toast(self._update_status)
            if automatic and self.store.get('notifications',True) and self.tray.isVisible():
                self.tray.showMessage('COKKER Converter',self._update_status)
            if self.current=='Настройки':self.show_settings()
        self.async_.run(work,ready)
    def start_update(self):
        if not self._release or self._update_busy:return
        if self.queue.active:self.toast('Дождитесь завершения активных задач.');return
        self.download_update(install_after=True)
    def _install_ready_update(self):
        if self.queue.active:
            self._update_status='Загрузка завершена. Дождитесь задач и повторите установку.'
            if self.current=='Настройки':self.show_settings()
            return
        if not self._update_ready or not Path(self._update_ready).is_file() or self._update_ready_version!=self._release.version:
            self._update_status='Файл обновления недоступен. Скачайте его ещё раз.'
            if self.current=='Настройки':self.show_settings()
            return
        portable=self._update_ready_kind=='portable';result=self._update_ready
        def launch(location):
            self._update_busy=False
            if isinstance(location,Exception):
                self._update_status='Не удалось подготовить обновление: '+str(location)
                if self.current=='Настройки':self.show_settings()
                return
            try:
                if portable:
                    subprocess.Popen([str(Path(location)/'COKKER Converter.exe'),'--apply-update',str(Path(sys.executable).parent),str(os.getpid())],cwd=location,close_fds=True)
                else:
                    subprocess.Popen([str(location),'/SP-','/NORESTART','/CLOSEAPPLICATIONS',f'/DIR={Path(sys.executable).parent}'],close_fds=True)
                self.exiting=True;self.close()
            except Exception as error:
                self._update_status='Не удалось запустить установку: '+str(error)
                if self.current=='Настройки':self.show_settings()
        if portable:
            self._update_busy=True;self._update_status='Подготавливаю Portable-обновление…'
            if self.current=='Настройки':self.show_settings()
            self.async_.run(lambda:prepare_portable(result,Path(tempfile.gettempdir())/f'COKKER-Update-{self._release.version}-{uuid.uuid4().hex[:8]}'),launch)
        else:launch(result)
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
        if not self.exiting and self._update_busy:
            self.cancel_update();self.toast('Дождитесь остановки загрузки обновления.');event.ignore();return
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
        self.notice.setText(text);self.notice.show();self.notice_timer.start(7000)
    def notice_timer_done(self):self.notice.hide()
    def error(self,e):
        msg=QMessageBox(self);msg.setIcon(QMessageBox.Icon.Warning);msg.setWindowTitle('COKKER Converter');msg.setText('Не удалось выполнить действие');msg.setInformativeText(str(e).splitlines()[-1][:300]);msg.setDetailedText(str(e));msg.exec()
