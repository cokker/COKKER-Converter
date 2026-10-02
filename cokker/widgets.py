from pathlib import Path
from PySide6.QtCore import Qt, QMimeData, QUrl, QRect, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QDrag, QPixmap, QPainter, QColor, QPen
from PySide6.QtWidgets import QListWidget, QAbstractItemView, QLabel, QWidget, QVBoxLayout, QPushButton, QScrollArea

class FileList(QListWidget):
    filesDropped=Signal(list)
    def __init__(self):
        super().__init__(); self.setAcceptDrops(True); self.setDragEnabled(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setMinimumHeight(130)
    def dragEnterEvent(self,e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
        else: super().dragEnterEvent(e)
    def dragMoveEvent(self,e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
        else: super().dragMoveEvent(e)
    def dropEvent(self,e):
        if e.mimeData().hasUrls(): self.filesDropped.emit([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]); e.acceptProposedAction()
        else: super().dropEvent(e)

class Results(QListWidget):
    def __init__(self):
        super().__init__(); self.setDragEnabled(True); self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    def startDrag(self,actions):
        urls=[]
        for item in self.selectedItems():
            p=item.data(Qt.ItemDataRole.UserRole+1)
            if p and Path(p).exists(): urls.append(QUrl.fromLocalFile(p))
        if urls:
            mime=QMimeData(); mime.setUrls(urls); drag=QDrag(self); drag.setMimeData(mime); drag.exec(Qt.DropAction.CopyAction)

class CropCanvas(QLabel):
    selected=Signal(str)
    def __init__(self):
        super().__init__(); self.source=QPixmap(); self.rect=QRect(); self.anchor=None
        self.setMinimumSize(400,260); self.setAlignment(Qt.AlignmentFlag.AlignCenter)
    def set_source(self,path): self.source=QPixmap(str(path)); self.rect=QRect(); self.update()
    def image_rect(self):
        if self.source.isNull(): return QRect()
        size=self.source.size(); size.scale(self.size(),Qt.AspectRatioMode.KeepAspectRatio)
        return QRect((self.width()-size.width())//2,(self.height()-size.height())//2,size.width(),size.height())
    def paintEvent(self,e):
        super().paintEvent(e)
        if self.source.isNull(): return
        p=QPainter(self); bounds=self.image_rect(); p.drawPixmap(bounds,self.source)
        if not self.rect.isNull(): p.setPen(QPen(QColor('#ff9c56'),2)); p.setBrush(QColor(255,156,86,35)); p.drawRect(self.rect)
    def mousePressEvent(self,e):
        if not self.source.isNull(): self.anchor=e.position().toPoint()
    def mouseMoveEvent(self,e):
        if self.anchor is not None: self.rect=QRect(self.anchor,e.position().toPoint()).normalized().intersected(self.image_rect()); self.update()
    def mouseReleaseEvent(self,e):
        if self.anchor is not None and self.rect.width()>2 and self.rect.height()>2:
            bounds=self.image_rect(); sx=self.source.width()/bounds.width(); sy=self.source.height()/bounds.height()
            vals=[round((self.rect.x()-bounds.x())*sx),round((self.rect.y()-bounds.y())*sy),round(self.rect.width()*sx),round(self.rect.height()*sy)]
            self.selected.emit(','.join(map(str,vals)))
        self.anchor=None

class Section(QWidget):
    def __init__(self,title,body,animate=lambda:True):
        super().__init__(); self.body=body; self.animate=animate; self.anim=None
        layout=QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        self.button=QPushButton('›  '+title); self.title=title; self.button.setCheckable(True)
        self.button.clicked.connect(self.toggle); layout.addWidget(self.button); layout.addWidget(body); body.hide()
    def toggle(self,checked):
        self.button.setText(('⌄  ' if checked else '›  ')+self.title)
        if not checked: self.body.hide(); return
        self.body.show()
        if self.animate():
            target=self.body.sizeHint().height(); self.anim=QPropertyAnimation(self.body,b'maximumHeight',self)
            self.anim.setDuration(180); self.anim.setStartValue(0); self.anim.setEndValue(target)
            self.anim.setEasingCurve(QEasingCurve.Type.OutCubic); self.anim.finished.connect(lambda:self.body.setMaximumHeight(16777215)); self.anim.start()
