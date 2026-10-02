"""Small scalable line icons for navigation and tool cards."""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

NAV_ICONS={
    'Главная':'home','Избранное':'star','Очередь':'queue','История':'history',
    'Видео':'video','Аудио':'audio','Изображения':'image','Документы':'document',
    'PDF':'pdf','Архивы':'archive','Электронные книги':'book','VRChat':'vr',
    'Настройки':'settings','О программе':'info',
}
CATEGORY_ICONS={'Видео':'video','Аудио':'audio','Изображения':'image','Документы':'document',
                'PDF':'pdf','Архивы':'archive','Электронные книги':'book','VRChat':'vr'}

def icon_for(name, color='#ff9c56'):
    kind=NAV_ICONS.get(name,CATEGORY_ICONS.get(name,name))
    pix=QPixmap(48,48);pix.fill(Qt.GlobalColor.transparent)
    painter=QPainter(pix);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(2,2);painter.setPen(QPen(QColor(color),1.8,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin));painter.setBrush(Qt.BrushStyle.NoBrush)
    def line(*xy): painter.drawLine(*xy)
    def rect(x,y,w,h,r=0): painter.drawRoundedRect(QRectF(x,y,w,h),r,r)
    def ellipse(x,y,w,h): painter.drawEllipse(QRectF(x,y,w,h))
    def path(points,closed=False):
        shape=QPainterPath();shape.moveTo(*points[0])
        for point in points[1:]:shape.lineTo(*point)
        if closed:shape.closeSubpath()
        painter.drawPath(shape)
    if kind=='home':
        path([(3,11),(12,3),(21,11)]);path([(5.5,10),(5.5,21),(18.5,21),(18.5,10)]);rect(10,14,4,7,1)
    elif kind=='star':
        path([(12,2.5),(15,8.4),(21.5,9.4),(17,14),(18,20.5),(12,17.3),(6,20.5),(7,14),(2.5,9.4),(9,8.4)],True)
    elif kind=='queue':
        for y in (5,12,19):ellipse(3,y-1,2,2);line(8,y,21,y)
    elif kind=='history':
        painter.drawArc(QRectF(3.5,3.5,17,17),-40*16,300*16);path([(3,3),(3,8),(8,8)]);line(12,7,12,12);line(12,12,16,14)
    elif kind=='video':
        rect(2.5,5,19,14,2.8);path([(10,8.5),(16,12),(10,15.5)],True)
    elif kind=='audio':
        path([(10,17),(10,5),(19,3),(19,15)]);ellipse(5,16,5,3.5);ellipse(14,14,5,3.5)
    elif kind=='image':
        rect(3,4,18,16,2.5);ellipse(14.5,7,3,3);path([(4,17),(9,12),(12,15),(15,12),(20,18)])
    elif kind in ('document','pdf'):
        path([(5,2.5),(15,2.5),(20,7.5),(20,21),(5,21)],True);path([(15,2.5),(15,7.5),(20,7.5)])
        if kind=='pdf': path([(8,13),(11,16),(16,11)] )
        else:line(8,12,16,12);line(8,16,15,16)
    elif kind=='archive':
        rect(3,8,18,13,2);path([(3,8),(5,4),(19,4),(21,8)]);line(3,9,21,9);rect(10,8,4,5,1)
    elif kind=='book':
        path([(12,20),(12,5),(9,3),(3,3),(3,18),(9,18),(12,20)]);path([(12,20),(15,18),(21,18),(21,3),(15,3),(12,5)])
    elif kind=='vr':
        rect(2,7,20,11,4);rect(5,10,5,4,1);rect(14,10,5,4,1);line(10,16,14,16)
    elif kind=='settings':
        ellipse(5,5,14,14);ellipse(9,9,6,6)
        for a,b,c,d in ((12,2,12,5),(12,19,12,22),(2,12,5,12),(19,12,22,12),(5,5,7,7),(17,17,19,19),(5,19,7,17),(17,7,19,5)):line(a,b,c,d)
    elif kind=='info':
        ellipse(3,3,18,18);ellipse(11,7,2,2);line(12,11,12,17)
    painter.end();return QIcon(pix)
