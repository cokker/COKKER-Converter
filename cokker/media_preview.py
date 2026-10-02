"""Inline preview of the selected source and image adjustments."""
from pathlib import Path
import os
from PySide6.QtCore import Qt, QUrl, QSize, QRect
from PySide6.QtGui import QMovie, QPixmap, QPainter, QColor, QPen
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout, QHBoxLayout, QStackedWidget, QPushButton, QSlider
from .registry import file_kind

class ComparisonCanvas(QWidget):
    """Reveal the processed frame over the original with a movable divider."""
    def __init__(self,parent=None):
        super().__init__(parent);self.before=QPixmap();self.after=QPixmap();self.percent=50
        self.setMinimumHeight(260)
    def set_images(self,before,after):
        self.before=before;self.after=after;self.update()
    def set_percent(self,percent):self.percent=percent;self.update()
    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(),QColor('#121922'))
        split=round(self.width()*self.percent/100)
        def frame(pix):
            if pix.isNull():return
            dimensions=pix.size();dimensions.scale(self.size(),Qt.AspectRatioMode.KeepAspectRatio)
            bounds=QRect((self.width()-dimensions.width())//2,(self.height()-dimensions.height())//2,dimensions.width(),dimensions.height())
            p.drawPixmap(bounds,pix)
        p.save();p.setClipRect(QRect(0,0,split,self.height()));frame(self.before);p.restore()
        p.save();p.setClipRect(QRect(split,0,self.width()-split,self.height()));frame(self.after);p.restore()
        p.setPen(QPen(QColor('#ff9c56'),2));p.drawLine(split,0,split,self.height())
        p.setBrush(QColor('#ff9c56'));p.drawEllipse(split-6,self.height()//2-6,12,12)
        p.end()

class MediaPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = None
        self.original = QPixmap()
        self.source_pixmap = QPixmap()
        self.movie = None
        self.player = None
        self.audio = None
        self._video = None
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(9)
        self.view = QStackedWidget(); self.view.setMinimumHeight(260)
        self.picture = QLabel('Выберите файл для просмотра'); self.picture.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.picture.setObjectName('mediaPreview'); self.view.addWidget(self.picture)
        self.comparison=ComparisonCanvas();self.view.addWidget(self.comparison)
        layout.addWidget(self.view)
        compare_controls=QHBoxLayout();compare_controls.addWidget(QLabel('Исходник'))
        self.compare_slider=QSlider(Qt.Orientation.Horizontal);self.compare_slider.setValue(50)
        self.compare_slider.valueChanged.connect(self.comparison.set_percent)
        compare_controls.addWidget(self.compare_slider,1);compare_controls.addWidget(QLabel('После изменений'))
        self.compare_back=QPushButton('Вернуться к видео');self.compare_back.clicked.connect(self.back_to_video)
        compare_controls.addWidget(self.compare_back)
        self.compare_controls=QWidget();self.compare_controls.setLayout(compare_controls)
        layout.addWidget(self.compare_controls);self.compare_controls.hide()
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
        self.original = QPixmap();self.source_pixmap=QPixmap();self.controls.hide();self.compare_controls.hide();self.view.setCurrentWidget(self.picture)
        self.picture.setText('Выберите файл для просмотра' if not path else 'Предпросмотр недоступен для этого формата')
        self.details.setText('')
        if not path: return
        kind = file_kind(path)
        if kind == 'image' and Path(path).suffix.lower() == '.gif':
            self.movie = QMovie(path)
            self.picture.setMovie(self.movie); self.movie.start(); self.fit_movie(); self.controls.show()
            self.timeline.setRange(0, 0); self.timeline.hide(); self.play.setText('⏸  Пауза')
        elif kind == 'image':
            self.source_pixmap=QPixmap(path);self.show_pixmap(self.source_pixmap)
        elif kind in ('video', 'audio') and self.player:
            self.player.setSource(QUrl.fromLocalFile(path)); self.controls.show(); self.timeline.show()
            if kind == 'video': self.view.setCurrentWidget(self._video)
            else: self.picture.setText('♪  Аудиозапись')
        else: self.picture.setText('Для этого файла визуальный просмотр недоступен')

    def show_pixmap(self, pixmap):
        self.original = pixmap
        if pixmap.isNull(): self.picture.setText('Не удалось прочитать изображение'); return
        if not self.source_pixmap.isNull():
            self.comparison.set_images(self.source_pixmap,pixmap)
            self.view.setCurrentWidget(self.comparison);self.compare_controls.show();self.compare_back.hide()
            return
        self.picture.setPixmap(pixmap.scaled(max(1,self.picture.width()-12), max(1,self.picture.height()-12),
                                              Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def show_video_comparison(self,before,after):
        if self.player:self.player.pause()
        self.comparison.set_images(before,after);self.view.setCurrentWidget(self.comparison)
        self.compare_controls.show();self.compare_back.show()

    def back_to_video(self):
        if self._video and self.player:
            self.view.setCurrentWidget(self._video);self.compare_controls.hide()

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
