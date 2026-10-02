"""Inline preview of the selected source and image adjustments."""
from pathlib import Path
import os
from PySide6.QtCore import Qt, QUrl, QSize
from PySide6.QtGui import QMovie, QPixmap
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QStackedWidget, QPushButton, QSlider
from .registry import file_kind

class MediaPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = None
        self.original = QPixmap()
        self.movie = None
        self.player = None
        self.audio = None
        self._video = None
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(9)
        self.view = QStackedWidget(); self.view.setMinimumHeight(260)
        self.picture = QLabel('Выберите файл для просмотра'); self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture.setObjectName('mediaPreview'); self.view.addWidget(self.picture)
        layout.addWidget(self.view)
        controls = QHBoxLayout(); self.play = QPushButton('▶  Воспроизвести')
        self.play.clicked.connect(self.toggle_play); self.timeline = QSlider(Qt.Orientation.Horizontal)
        self.timeline.sliderMoved.connect(self.seek)
        controls.addWidget(self.play); controls.addWidget(self.timeline, 1)
        self.controls = QWidget(); self.controls.setLayout(controls); layout.addWidget(self.controls)
        self.controls.hide()
        self.details = QLabel(''); self.details.setWordWrap(True); self.details.setObjectName('subtitle')
        layout.addWidget(self.details)
        try:
            if os.environ.get('QT_QPA_PLATFORM') == 'offscreen': raise ImportError('No video surface in offscreen tests')
            from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
            from PySide6.QtMultimediaWidgets import QVideoWidget
            self._video = QVideoWidget(); self.view.addWidget(self._video)
            self.player = QMediaPlayer(self); self.audio = QAudioOutput(self)
            self.player.setAudioOutput(self.audio); self.player.setVideoOutput(self._video)
            self.player.positionChanged.connect(self.timeline.setValue)
            self.player.durationChanged.connect(self.timeline.setMaximum)
            self.player.playbackStateChanged.connect(lambda state: self.play.setText('⏸  Пауза' if state == QMediaPlayer.PlaybackState.PlayingState else '▶  Воспроизвести'))
            self.player.errorOccurred.connect(lambda *args: self.details.setText(self.details.text()+'\nВоспроизведение не поддерживается системными кодеками.'))
        except ImportError:
            pass

    def set_file(self, path):
        if path == self.path: return
        self.path = path
        if self.movie: self.movie.stop(); self.movie.deleteLater(); self.movie = None
        if self.player: self.player.stop(); self.player.setSource(QUrl())
        self.original = QPixmap(); self.controls.hide(); self.view.setCurrentWidget(self.picture)
        self.picture.setText('Выберите файл для просмотра' if not path else 'Предпросмотр недоступен для этого формата')
        self.details.setText('')
        if not path: return
        kind = file_kind(path)
        if kind == 'image' and Path(path).suffix.lower() == '.gif':
            self.movie = QMovie(path)
            self.picture.setMovie(self.movie); self.movie.start(); self.fit_movie(); self.controls.show()
            self.timeline.setRange(0, 0); self.timeline.hide(); self.play.setText('⏸  Пауза')
        elif kind == 'image':
            self.original = QPixmap(path); self.show_pixmap(self.original)
        elif kind in ('video', 'audio') and self.player:
            self.player.setSource(QUrl.fromLocalFile(path)); self.controls.show(); self.timeline.show()
            if kind == 'video': self.view.setCurrentWidget(self._video)
            else: self.picture.setText('♪  Аудиозапись')
        else: self.picture.setText('Для этого файла визуальный просмотр недоступен')

    def show_pixmap(self, pixmap):
        self.original = pixmap
        if pixmap.isNull(): self.picture.setText('Не удалось прочитать изображение'); return
        self.picture.setPixmap(pixmap.scaled(max(1,self.picture.width()-12), max(1,self.picture.height()-12),
                                              Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.original.isNull(): self.show_pixmap(self.original)
        if self.movie: self.fit_movie()

    def fit_movie(self):
        frame=self.movie.currentPixmap().size()
        if frame.isEmpty():return
        frame.scale(QSize(max(1,self.picture.width()-12),max(1,self.picture.height()-12)),Qt.AspectRatioMode.KeepAspectRatio)
        self.movie.setScaledSize(frame)

    def toggle_play(self):
        if self.movie:
            if self.movie.state() == QMovie.MovieState.Running: self.movie.setPaused(True); self.play.setText('▶  Воспроизвести')
            else: self.movie.setPaused(False); self.play.setText('⏸  Пауза')
        elif self.player:
            from PySide6.QtMultimedia import QMediaPlayer
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState: self.player.pause()
            else: self.player.play()

    def seek(self, position):
        if self.player and not self.movie: self.player.setPosition(position)
