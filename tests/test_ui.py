import os,tempfile
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
