import sys, os, json, logging, hashlib
from logging.handlers import RotatingFileHandler
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalServer,QLocalSocket
from PySide6.QtWidgets import QApplication
from cokker.storage import root_dir
from cokker.ui import Window

def main():
    app=QApplication(sys.argv);app.setApplicationName('COKKER Converter');app.setOrganizationName('COKKER');app.setQuitOnLastWindowClosed(False)
    root=root_dir();root.mkdir(parents=True,exist_ok=True);logs=root/'logs';logs.mkdir(exist_ok=True)
    handler=RotatingFileHandler(logs/'app.log',maxBytes=10*1024*1024,backupCount=4,encoding='utf-8');logging.basicConfig(level=logging.INFO,handlers=[handler])
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
