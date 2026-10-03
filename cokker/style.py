def stylesheet(theme='dark'):
    light=theme=='light'
    bg='#f4f6f9' if light else '#10151d'; panel='#ffffff' if light else '#1b2430'
    fg='#202936' if light else '#f1f4f8'; muted='#667487' if light else '#a9b5c6'; border='#dbe2e9' if light else '#334154'
    hover='#fff0e3' if light else '#2c3540';selected='#ffe9d5' if light else '#493a32'
    return f'''
    QWidget {{ background:{bg}; color:{fg}; font-family:"Segoe UI","DejaVu Sans"; font-size:14px; }}
    QMainWindow {{ background:{bg}; }}
    QLabel {{ background:transparent; }}
    QLabel#title {{font-size:28px;font-weight:700;}}
    QLabel#subtitle {{color:{muted};font-size:13px;}}
    QLabel#brand {{font-size:20px;font-weight:800;color:#ff9c56;padding:0;}}
    QFrame#card,QGroupBox {{background:{panel};border:1px solid {border};border-radius:16px;padding:14px;}}
    QWidget#componentRow {{background:transparent;}}
    QGroupBox {{margin-top:12px;}}
    QGroupBox::title {{subcontrol-origin:margin;left:18px;padding:0 6px;}}
    QPushButton {{background:{panel};border:1px solid {border};border-radius:10px;padding:10px 13px;text-align:left;min-height:22px;}}
    QPushButton:hover {{border-color:#ff9c56;background:{hover};}}
    QPushButton:pressed {{background:{selected};}}
    QPushButton:focus {{border-color:#ff9c56;}}
    QPushButton:disabled {{color:{muted};}}
    QPushButton#primary {{background:#ff9c56;color:#19130f;font-weight:700;border:1px solid #ff9c56;text-align:center;}}
    QPushButton#primary:hover {{background:#ffb979;}}
    QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox {{background:{panel};border:1px solid {border};border-radius:9px;padding:8px;min-height:22px;}}
    QFrame#card QLineEdit,QFrame#card QComboBox,QFrame#card QSpinBox,QFrame#card QDoubleSpinBox {{background:{panel};}}
    QLineEdit:focus,QComboBox:focus,QSpinBox:focus,QDoubleSpinBox:focus {{border-color:#ff9c56;}}
    QComboBox::drop-down {{border:0;width:22px;}}
    QComboBox QAbstractItemView {{background:{panel};selection-background-color:#6a4227;}}
    QListWidget {{background:{panel};border:1px solid {border};border-radius:12px;padding:8px;outline:0;}}
    QListWidget::item {{padding:11px;border-radius:9px;}}
    QListWidget::item:selected {{background:{selected};color:{fg};}}
    QListWidget#nav {{background:transparent;border:0;padding:0 7px 0 0;}}
    QListWidget#nav::item {{padding:9px 12px;margin:2px 10px 2px 0;border-radius:10px;}}
    QListWidget#nav::item:hover {{background:{hover};}}
    QListWidget#nav::item:selected {{background:{selected};color:{fg};font-weight:600;}}
    QScrollArea {{border:0;background:transparent;}}
    QScrollBar:vertical {{background:transparent;width:10px;margin:0;}}
    QScrollBar::handle:vertical {{background:{border};border-radius:5px;min-height:30px;}}
    QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}
    QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {{background:transparent;}}
    QProgressBar {{border:0;background:{panel};border-radius:7px;min-height:14px;text-align:center;}}
    QProgressBar::chunk {{background:#ff9c56;border-radius:7px;}}
    QCheckBox {{spacing:10px;padding:6px 0;background:transparent;}}
    QCheckBox:hover {{color:#ffb979;}}
    QCheckBox::indicator {{width:17px;height:17px;border:1px solid {border};border-radius:5px;background:{panel};}}
    QCheckBox::indicator:checked {{background:#ff9c56;}}
    QSlider {{background:transparent;min-height:24px;}}
    QSlider::groove:horizontal {{height:7px;background:{border};border-radius:3px;}}
    QSlider::sub-page:horizontal {{background:#ff9c56;border-radius:3px;}}
    QSlider::handle:horizontal {{background:#ffd0a1;border:2px solid #ff9c56;width:17px;height:17px;margin:-6px 0;border-radius:10px;}}
    QSlider::handle:horizontal:hover {{background:#ffffff;}}
    QToolTip {{color:{fg};background:{panel};border:1px solid {border};padding:8px;}}
    QSplitter::handle {{background:transparent;width:12px;}}
    '''
