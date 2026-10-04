"""One set of global input hooks per user, with local launch forwarding."""
import hashlib
import json
from pathlib import Path
from PyQt6.QtCore import QLockFile, QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    requested = pyqtSignal(str)

    def __init__(self, directory, parent=None):
        super().__init__(parent)
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        self.name = 'meikipop-' + hashlib.sha256(str(directory).encode()).hexdigest()[:20]
        self.lock = QLockFile(str(directory / 'quick-lookup.lock'))
        self.lock.setStaleLockTime(0)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self.receive)

    def start(self, text='', background=False):
        if not self.lock.tryLock(0):
            if not background or text:
                socket = QLocalSocket(self)
                socket.connectToServer(self.name)
                if socket.waitForConnected(500):
                    socket.write((json.dumps(text) + '\n').encode())
                    socket.waitForBytesWritten(500)
                    socket.disconnectFromServer()
                socket.deleteLater()
            return False
        QLocalServer.removeServer(self.name)
        if not self.server.listen(self.name):
            self.lock.unlock()
            raise RuntimeError(self.server.errorString())
        return True

    def receive(self):
        socket = self.server.nextPendingConnection()
        def read():
            if socket.canReadLine():
                try:
                    text = json.loads(bytes(socket.readLine(16384)))
                    if isinstance(text, str):
                        self.requested.emit(text[:2000])
                except (ValueError, UnicodeError):
                    pass
                socket.disconnectFromServer()
        socket.readyRead.connect(read)
        socket.disconnected.connect(socket.deleteLater)
        read()

    def shutdown(self):
        self.server.close()
        self.lock.unlock()
