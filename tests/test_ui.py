import os,tempfile,subprocess,time,sys
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication,QDialog,QMessageBox,QPushButton
from PySide6.QtCore import qInstallMessageHandler
from PIL import Image
from cokker.storage import Store
from cokker.ui import Window
from cokker.registry import compatible_operations, file_kind
from cokker.registry import REGISTRY
from cokker.updater import Release

def test_navigation_and_shortcuts():
    app=QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        window=Window(Store(Path(tmp)))
        for page in ('Главная','Видео','Аудио','Изображения','PDF','Избранное','Очередь','История','Настройки','О программе'):
            window.navigate(page)
            assert window.pages.currentWidget() is not None
        window.set_operation('image')
        assert window.operation.currentData()=='image'
        window.exiting=True;window.close()

def test_automatic_file_actions_and_brand():
    app=QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);picture=root/'photo.png';Image.new('RGB',(8,8),'orange').save(picture)
        renamed=root/'picture.data';renamed.write_bytes(picture.read_bytes())
        video=root/'clip.mp4';video.write_bytes(b'placeholder for UI selection')
        assert file_kind(renamed)=='image'
        assert 'video' not in {op.id for op in compatible_operations([picture])}
        window=Window(Store(root/'settings'))
        assert not window.icon.isNull()
        with Image.open(Path(__file__).parents[1]/'assets'/'logo.png') as logo:
            assert logo.mode=='RGBA' and logo.getpixel((0,0))[3]==0
        with Image.open(Path(__file__).parents[1]/'assets'/'logo.ico') as ico:
            assert ico.convert('RGBA').getpixel((0,0))[3]==0
        assert all(not window.nav.item(i).icon().isNull() for i in range(window.nav.count()))
        window.receive_paths([str(picture)])
        assert window.operation.currentData()=='image'
        assert {window.operation.itemData(i) for i in range(window.operation.count())}=={'image'}
        assert not window.size_row.isHidden() and window.size_row.parentWidget().objectName()=='card'
        assert '*.mp4' not in window.section_file_filter()
        window.receive_paths([str(video)])
        assert window.input_paths()==[str(picture)] # The image section rejects a video.
        window.navigate('Архивы');window.receive_paths([str(video)])
        assert window.operation.currentData()=='archive' and len(window.input_paths())==2
        window.files.item(1).setSelected(True);window.remove_inputs()
        window.navigate('Изображения')
        assert window.operation.currentData()=='image'
        window.files.item(0).setSelected(True);window.remove_inputs()
        assert {window.operation.itemData(i) for i in range(window.operation.count())}=={'image','images_gif'}
        window.navigate('Главная')
        window.receive_paths([str(video)])
        video_actions={window.operation.itemData(i) for i in range(window.operation.count())}
        assert window.operation.currentData()=='video'
        assert {'video','remux','mute','video_gif'} <= video_actions
        assert 'audio' not in video_actions
        assert 'image' not in video_actions and 'pdf_merge' not in video_actions
        assert REGISTRY['video_gif'].category=='Видео'
        window.navigate('Аудио');assert window.operation.currentData()=='audio'
        window.navigate('Видео');assert 'video_gif' in {window.operation.itemData(i) for i in range(window.operation.count())}
        document=root/'paper.txt';document.write_text('text',encoding='utf-8')
        window.navigate('Документы');window.receive_paths([str(picture),str(document)])
        assert window.input_paths()==[str(document)]
        assert window.operation.currentData()=='document'
        window.exiting=True;window.close()

def test_source_metadata_visible_options_and_quick_favorite():
    app=QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);picture=root/'scene.png';Image.new('RGB',(320,180),'orange').save(picture)
        window=Window(Store(root/'settings'))
        window.use_quick('image','jpg')
        window.receive_paths([str(picture)])
        for _ in range(100):
            app.processEvents()
            if window.controls['width'].value()==320:break
            import time;time.sleep(.01)
        assert window.controls['width'].value()==320
        assert window.controls['height'].value()==180
        assert window.format.currentText()=='jpg'
        assert window.media_preview.path==str(picture)
        assert window.media_preview.view.currentWidget() is window.media_preview.comparison
        assert '320 × 180' in window.media_preview.details.text()
        assert 'fps' not in window._visible_options
        assert 'sample_rate' not in window._visible_options
        assert 'fps' in window.controls['fps'].toolTip().lower() or 'Кадров' in window.controls['fps'].toolTip()
        window.controls['width'].setValue(160)
        assert window.controls['height'].value()==90
        window.resolution.setCurrentText('512 × 512')
        assert (window.controls['width'].value(),window.controls['height'].value())==(512,512)
        window.controls['width'].setValue(160)
        assert window.options().width==160
        window.size_slider.setValue(50)
        assert 0<window.controls['target_mb'].value()<picture.stat().st_size/1048576
        assert '50%' in window.size_percent.text() and 'цель' in window.size_hint.text()
        window.add_favorite()
        saved=window.presets.all();assert saved[-1]['parameters']['width']==160
        window.navigate('Избранное')
        assert window.pages.currentWidget() is window.extra
        window.exiting=True;window.close()

def test_home_detects_jpeg_and_size_control_for_png():
    app=QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);photo=root/'photo.jpg';png=root/'icon.png'
        Image.new('RGB',(800,600),'orange').save(photo,quality=95)
        Image.new('RGB',(800,600),'blue').save(png)
        window=Window(Store(root/'settings'));window.navigate('Главная')
        window.receive_paths([str(photo)])
        for _ in range(100):
            app.processEvents();time.sleep(.01)
            if window._source_bytes:break
        assert window.current=='Изображения' and window.pages.currentWidget() is window.editor
        assert window.operation.currentData()=='image' and window.format.currentText()=='jpg'
        assert not window.size_row.isHidden()
        window.size_slider.setValue(60)
        assert window.options().target_mb>0
        window.files.item(0).setSelected(True);window.remove_inputs()
        window.receive_paths([str(png)])
        for _ in range(100):
            app.processEvents();time.sleep(.01)
            if window._source_bytes==png.stat().st_size:break
        assert window.format.currentText()=='png' and not window.size_row.isHidden()
        window.size_slider.setValue(75)
        assert window.options().target_mb>0 and 'разрешение' in window.size_hint.text()
        window.exiting=True;window.close()

def test_video_frame_comparison_uses_current_settings():
    app=QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);video=root/'clip.mp4'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=orange:s=160x120:r=10',
                        '-t','1','-c:v','mpeg4','-y',str(video)],check=True)
        window=Window(Store(root/'settings'));window.receive_paths([str(video)])
        for _ in range(100):
            app.processEvents();time.sleep(.01)
            if window.controls['width'].value()==160:break
        window.controls['width'].setValue(80)
        window.compare_video_frame()
        for _ in range(150):
            app.processEvents();time.sleep(.01)
            if not window.media_preview.comparison.after.isNull():break
        assert window.media_preview.comparison.before.width()==160
        assert window.media_preview.comparison.after.width()==80
        window.exiting=True;window.close()

def test_convert_now_opens_history_with_before_after_preview():
    app=QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);picture=root/'original.png';Image.new('RGB',(120,80),'orange').save(picture)
        window=Window(Store(root/'settings'));window.receive_paths([str(picture)])
        window.format.setCurrentText('jpg');window.output.setText(str(root/'output'))
        window.convert_now()
        for _ in range(300):
            app.processEvents();time.sleep(.01)
            if window.current=='История' and not window.history_preview.comparison.after.isNull():break
        assert window.current=='История'
        assert window.pages.currentWidget() is window.history_page
        assert window.history_list.count()==1 and window.queue_list.count()==1
        assert not window.history_preview.comparison.before.isNull()
        assert not window.history_preview.comparison.after.isNull()
        window.exiting=True;window.close()

def test_editor_buttons_after_adding_png(monkeypatch):
    app=QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);picture=root/'photo.png';Image.new('RGB',(64,48),'orange').save(picture)
        folder=root/'more';folder.mkdir();extra=folder/'extra.png';Image.new('RGB',(24,24),'blue').save(extra)
        window=Window(Store(root/'settings'));window.navigate('Изображения')
        class Selection:
            def __init__(self,path):self.path=path
            def exec(self):return QDialog.DialogCode.Accepted
            def selectedFiles(self):return [str(self.path)]
        window.files_dialog=lambda:Selection(picture)
        window.folder_dialog=lambda:Selection(folder)
        messages=[];monkeypatch.setattr(QMessageBox,'information',lambda *args:messages.append(args[-1]))
        monkeypatch.setattr(QDialog,'exec',lambda self:QDialog.DialogCode.Rejected)
        window.async_.run=lambda fn,callback:callback(fn())
        window.show();app.processEvents()
        buttons={b.text():b for b in window.editor.findChildren(QPushButton)}
        warnings=[];previous=qInstallMessageHandler(lambda kind,context,message:warnings.append(message))
        try:
            for name in ('Добавить','Папка','Удалить выбранные','Информация','Preview / Crop'):
                control=buttons[name];control.set_accent(1);control.set_press(1);control.grab()
                control.set_press(0);control.set_accent(0)
            buttons['Добавить'].click()
            assert len(window.input_paths())==1 and Path(window.input_paths()[0]).samefile(picture)
            buttons['Папка'].click()
            assert len(window.input_paths())==2 and all(Path(actual).samefile(expected) for actual,expected in zip(window.input_paths(),(picture,extra)))
            buttons['Информация'].click()
            assert messages and '64 × 48' in messages[-1]
            buttons['Preview / Crop'].click()
            window.files.item(1).setSelected(True)
            buttons['Удалить выбранные'].click()
            assert len(window.input_paths())==1 and Path(window.input_paths()[0]).samefile(picture)
        finally:
            qInstallMessageHandler(previous)
            window.exiting=True;window.close()
        assert not any('QPainter' in warning for warning in warnings)

def test_update_notification_and_opt_in_download(monkeypatch):
    app=QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);window=Window(Store(root/'settings'))
        window.async_.run=lambda fn,callback:callback(fn())
        release=Release('v99.0.0','https://github.com/cokker/COKKER-Converter/releases/tag/v99.0.0',{})
        monkeypatch.setattr('cokker.ui.check_release',lambda version:release)
        window.check_update(automatic=True)
        assert window._release==release and window.update_badge.isHidden() is False
        assert window.store.get('update_notified_version')==release.version
        assert window._update_ready is None
        if os.name=='nt':
            monkeypatch.setattr(sys,'frozen',True,raising=False)
            window.store.set('update_auto_download',True)
            def fake_download(release,kind,folder,progress,cancel):
                folder.mkdir(parents=True,exist_ok=True)
                target=folder/'download.exe';target.write_bytes(b'test')
                progress(100);return target
            monkeypatch.setattr('cokker.ui.download',fake_download)
            window.check_update(automatic=True)
            app.processEvents()
            assert window._update_ready.is_file() and window._update_ready_kind=='setup'
            assert window.update_badge.text().startswith('Установить')
        window.exiting=True;window.close()
