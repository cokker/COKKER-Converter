from dataclasses import dataclass, field, asdict
import uuid

@dataclass
class Options:
    format: str = 'mp4'
    quality: int = 82
    codec: str = 'auto'
    width: int = 0
    height: int = 0
    scale_mode: str = 'fit'
    no_upscale: bool = True
    fps: float = 0
    speed: float = 1
    start: float = 0
    end: float = 0
    crop: str = ''
    rotate: int = 0
    flip: str = 'none'
    audio_bitrate: int = 192
    sample_rate: int = 0
    channels: int = 0
    normalize: bool = False
    volume: float = 1
    strip_metadata: bool = True
    target_mb: float = 0
    hardware: str = 'cpu'
    extra_file: str = ''
    frame_ms: int = 100
    frame_delays: str = ''
    loop: int = 0
    emoji_frames: int = 64
    pages: str = ''
    def validate(self):
        if not 1 <= self.quality <= 100: raise ValueError('Качество: от 1 до 100.')
        if not .1 <= self.speed <= 16: raise ValueError('Скорость: от 0.1 до 16.')
        if self.start < 0 or self.end < 0 or (self.end and self.end <= self.start):
            raise ValueError('Конец должен быть позже начала.')
        if not 0 <= self.width <= 16384 or not 0 <= self.height <= 16384: raise ValueError('Размер: 0–16384.')
        if not 0 <= self.fps <= 240: raise ValueError('FPS: 0–240.')
        if not 0 <= self.target_mb <= 1048576: raise ValueError('Некорректный размер.')
        if self.rotate not in (0,90,180,270): raise ValueError('Некорректный угол.')
        if self.flip not in ('none','horizontal','vertical'): raise ValueError('Некорректное отражение.')
        if self.scale_mode not in ('fit','fill','stretch'): raise ValueError('Некорректный режим размера.')
        if self.hardware not in ('cpu','auto','nvenc','amf','qsv'): raise ValueError('Некорректный GPU.')
        if not 8 <= self.audio_bitrate <= 512: raise ValueError('Битрейт: 8–512.')
        if not 0 <= self.sample_rate <= 192000 or self.channels not in (0,1,2): raise ValueError('Некорректное аудио.')
        if not 0 <= self.volume <= 10: raise ValueError('Громкость: 0–10.')
        if self.emoji_frames not in (4,16,64): raise ValueError('Кадры: 4, 16 или 64.')
        if not 20 <= self.frame_ms <= 60000 or not 0 <= self.loop <= 65535: raise ValueError('Некорректная анимация.')
        if self.crop:
            vals = [int(v.strip()) for v in self.crop.split(',')]
            if len(vals) != 4 or min(vals[:2]) < 0 or min(vals[2:]) <= 0: raise ValueError('Crop: X,Y,ширина,высота.')
        if self.frame_delays:
            if any(not 20 <= int(x) <= 60000 for x in self.frame_delays.split(',')): raise ValueError('Длительности: 20–60000 мс.')

@dataclass
class Job:
    inputs: list[str]
    operation: str
    options: dict
    output_dir: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = 'waiting'
    progress: float = 0
    output: str = ''
    error: str = ''
    before: int = 0
    after: int = 0
    elapsed: float = 0
    created: str = ''
    def serialize(self): return asdict(self)
