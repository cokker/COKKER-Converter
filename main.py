import sys, os, json, logging, hashlib, faulthandler
from logging.handlers import RotatingFileHandler
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalServer,QLocalSocket
from PySide6.QtWidgets import QApplication,QPushButton,QDialog
from cokker.storage import root_dir
from cokker.ui import Window

def main():
    if '--apply-update' in sys.argv:
        from PySide6.QtWidgets import QMessageBox
        from cokker.updater import apply_portable
        index=sys.argv.index('--apply-update')
        app=QApplication(sys.argv)
        try:
            apply_portable(Path(sys.executable).parent,sys.argv[index+1],int(sys.argv[index+2]))
            return 0
        except Exception as error:
            QMessageBox.critical(None,'Обновление COKKER Converter',f'Не удалось заменить Portable-версию:\n{error}\n\nПредыдущая версия осталась в папке программы.')
            return 1
    app=QApplication(sys.argv);app.setApplicationName('COKKER Converter');app.setOrganizationName('COKKER');app.setQuitOnLastWindowClosed(False)
    if '--self-test' in sys.argv:
        import tempfile
        from PIL import Image
        from cokker.storage import Store
        from cokker.models import Job,Options
        from cokker.engine import Engine
        from cokker.platform_services import executable
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);image=folder/'input.png';Image.new('RGB',(100,80),(255,120,35)).save(image)
            window=Window(Store(folder/'settings'));window.navigate('Настройки');window.navigate('Очередь')
            if not window.icon.availableSizes(): raise RuntimeError('Логотип не включён в сборку')
            window.navigate('Изображения')
            class SelectedFile:
                def exec(self): return QDialog.DialogCode.Accepted
                def selectedFiles(self): return [str(image)]
            window.files_dialog=lambda:SelectedFile()
            add=next(b for b in window.editor.findChildren(QPushButton) if b.text()=='Добавить')
            add.click()
            import time
            for _ in range(200):
                app.processEvents()
                if window.input_paths():break
                time.sleep(.01)
            if window.input_paths()!=[str(image)]:raise RuntimeError('Кнопка «Добавить» не загрузила PNG')
            if window.operation.currentData()!='image' or window.operation.count()!=3: raise RuntimeError('Автоопределение PNG не работает')
            window.exiting=True;window.close()
            Engine().convert(Job([str(image)],'image',Options(format='webp').__dict__,str(folder)))
            if not executable('ffmpeg') or not executable('ffprobe'): raise RuntimeError('FFmpeg отсутствует в сборке')
            source=folder/'source.mp4'
            Engine().runner.run([executable('ffmpeg'),'-v','error','-f','lavfi','-i','testsrc2=size=64x64:rate=24','-t','0.5','-c:v','mpeg4','-y',str(source)])
            Engine().convert(Job([str(source)],'video',Options(format='webm').__dict__,str(folder)))
        return 0
    root=root_dir();root.mkdir(parents=True,exist_ok=True);logs=root/'logs';logs.mkdir(exist_ok=True)
    handler=RotatingFileHandler(logs/'app.log',maxBytes=10*1024*1024,backupCount=4,encoding='utf-8');logging.basicConfig(level=logging.INFO,handlers=[handler])
    crash_log=open(logs/'crash.log','a',encoding='utf-8')
    faulthandler.enable(file=crash_log,all_threads=True)
    key='COKKERConverter-'+hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:16]
    socket=QLocalSocket();socket.connectToServer(key)
    args=[str(Path(a).resolve()) for a in sys.argv[1:] if not a.startswith('--')]
    if socket.waitForConnected(500):
        socket.write(json.dumps(args).encode('utf-8')+b'\n');socket.waitForBytesWritten(1500);socket.disconnectFromServer();return 0
    server=QLocalServer();server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption);QLocalServer.removeServer(key)
    if not server.listen(key):raise RuntimeError('Не удалось запустить IPC-сервер.')
    window=Window();connections=[]
    def connection():
        client=server.nextPendingConnection();connections.append(client);buf=bytearray()
        def read():
            buf.extend(bytes(client.readAll()))
            if b'\n' in buf:
                try:
                    paths=json.loads(bytes(buf).split(b'\n')[0]);window.add_paths(paths);window.reveal()
                except Exception:logging.exception('IPC message rejected')
                client.disconnectFromServer()
        client.readyRead.connect(read);client.disconnected.connect(client.deleteLater)
        if client.bytesAvailable():read()
    server.newConnection.connect(connection)
    if '--tray' not in sys.argv or not window.tray.isVisible():window.show()
    if args:QTimer.singleShot(0,lambda:window.add_paths(args))
    return app.exec()

if __name__=='__main__':sys.exit(main())
