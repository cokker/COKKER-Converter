import os,tempfile
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from cokker.storage import Store
from cokker.ui import Window

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
