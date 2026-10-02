import os,tempfile,subprocess,time
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from PIL import Image
from cokker.storage import Store
from cokker.ui import Window
from cokker.registry import compatible_operations, file_kind

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
        assert all(not window.nav.item(i).icon().isNull() for i in range(window.nav.count()))
        window.receive_paths([str(picture)])
        assert window.operation.currentData()=='image'
        assert {window.operation.itemData(i) for i in range(window.operation.count())}=={'image','images_pdf','archive'}
        window.receive_paths([str(video)])
        assert window.operation.count()==1 and window.operation.currentData()=='archive'
        window.files.item(1).setSelected(True);window.remove_inputs()
        assert window.operation.currentData()=='image'
        window.files.item(0).setSelected(True);window.remove_inputs()
        assert window.operation.count()>10
        window.receive_paths([str(video)])
        video_actions={window.operation.itemData(i) for i in range(window.operation.count())}
        assert window.operation.currentData()=='video'
        assert {'video','remux','mute','video_gif','audio'} <= video_actions
        assert 'image' not in video_actions and 'pdf_merge' not in video_actions
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
        window.add_favorite()
        saved=window.presets.all();assert saved[-1]['parameters']['width']==160
        window.navigate('Избранное')
        assert window.pages.currentWidget() is window.extra
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
