"""Read source metadata without decoding whole media files."""
from pathlib import Path
from .registry import file_kind
from .platform_services import executable

def source_info(path):
    kind = file_kind(path)
    result = {'kind': kind, 'bytes': Path(path).stat().st_size}
    if kind == 'image':
        from PIL import Image
        with Image.open(path) as image:
            orientation=image.getexif().get(274,1)
            width,height=(image.height,image.width) if orientation in (5,6,7,8) else image.size
            result.update(width=width, height=height, format=image.format,
                          frames=getattr(image, 'n_frames', 1))
            if getattr(image, 'n_frames', 1) > 1:
                image.seek(0); result['frame_ms'] = image.info.get('duration', 100)
    elif kind in ('video', 'audio') and executable('ffprobe'):
        from .engine import Engine
        info = Engine().probe(path)
        result['duration'] = float(info.get('format', {}).get('duration') or 0)
        for stream in info.get('streams', []):
            if stream.get('codec_type') == 'video' and 'width' not in result:
                result['width'] = stream.get('width', 0); result['height'] = stream.get('height', 0)
                numerator, _, denominator = stream.get('avg_frame_rate', '0/1').partition('/')
                try: result['fps'] = round(float(numerator)/float(denominator), 3)
                except (ValueError, ZeroDivisionError): pass
            if stream.get('codec_type') == 'audio' and 'sample_rate' not in result:
                result['has_audio'] = True
                result['sample_rate'] = int(stream.get('sample_rate') or 0)
                result['channels'] = int(stream.get('channels') or 0)
    elif kind == 'pdf':
        from pypdf import PdfReader
        result['pages'] = len(PdfReader(path).pages)
    return result
