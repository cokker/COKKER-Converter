def stylesheet(theme='dark'):
    light=theme=='light'
    bg='#f5f6f8' if light else '#101217'; panel='#ffffff' if light else '#191d25'
    fg='#20252f' if light else '#ebedf3'; muted='#626b79' if light else '#929bab'; border='#dce0e6' if light else '#303744'
    return f'''
    QWidget {{ background:{bg}; color:{fg}; font-family:"Segoe UI","DejaVu Sans"; font-size:14px; }}
    QMainWindow {{ background:{bg}; }}
    QLabel {{ background:transparent; }}
    QLabel#title {{font-size:30px;font-weight:700;}}
    QLabel#subtitle {{color:{muted};font-size:14px;}}
    QLabel#brand {{font-size:21px;font-weight:800;color:#ff9c56;padding:12px;}}
    QFrame#card,QGroupBox {{background:{panel};border:1px solid {border};border-radius:14px;padding:16px;}}
    QGroupBox {{margin-top:12px;}}
    QGroupBox::title {{subcontrol-origin:margin;left:18px;padding:0 6px;}}
    QPushButton {{background:{panel};border:1px solid {border};border-radius:9px;padding:10px 16px;text-align:left;}}
    QPushButton:hover {{border-color:#ff9c56;background:{'#fff0e7' if light else '#2b2525'};}}
    QPushButton:pressed {{background:{'#ffe0cb' if light else '#413025'};}}
    QPushButton:disabled {{color:{muted};}}
    QPushButton#primary {{background:#ff9c56;color:#19130f;font-weight:700;border:0;text-align:center;}}
    QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox {{background:{panel};border:1px solid {border};border-radius:7px;padding:7px;min-height:20px;}}
    QComboBox::drop-down {{border:0;width:22px;}}
    QComboBox QAbstractItemView {{background:{panel};selection-background-color:#6a4227;}}
    QListWidget {{background:{panel};border:1px solid {border};border-radius:12px;padding:8px;outline:0;}}
    QListWidget::item {{padding:12px;border-radius:7px;}}
    QListWidget::item:selected {{background:{'#ffdfc9' if light else '#493222'};color:{fg};}}
    QListWidget#nav {{background:transparent;border:0;padding:0;}}
    QListWidget#nav::item {{padding:11px 14px;margin:2px 0;}}
    QScrollArea {{border:0;background:transparent;}}
    QScrollBar:vertical {{background:transparent;width:10px;margin:0;}}
    QScrollBar::handle:vertical {{background:{border};border-radius:5px;min-height:30px;}}
    QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {{height:0;}}
    QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {{background:transparent;}}
    QProgressBar {{border:0;background:{panel};border-radius:7px;min-height:14px;text-align:center;}}
    QProgressBar::chunk {{background:#ff9c56;border-radius:7px;}}
    QCheckBox {{spacing:10px;padding:6px 0;}}
    QCheckBox::indicator {{width:17px;height:17px;border:1px solid {border};border-radius:5px;background:{panel};}}
    QCheckBox::indicator:checked {{background:#ff9c56;}}
    QToolTip {{color:{fg};background:{panel};border:1px solid {border};padding:8px;}}
    QSplitter::handle {{background:transparent;width:12px;}}
    '''
