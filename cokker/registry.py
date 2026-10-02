from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Operation:
    id: str
    label: str
    category: str
    formats: tuple[str,...]
    backend: str
    multiple: bool = False

V = ('mp4','mkv','mov','avi','webm','wmv','m4v','mpeg','mpg','ts','mts','flv','3gp','ogv')
A = ('mp3','wav','flac','aac','m4a','ogg','opus','wma','aiff','ac3')
I = ('png','jpg','webp','avif','bmp','gif','tiff','ico')
OPERATIONS = [
 Operation('video','Конвертировать / сжать видео','Видео',V,'ffmpeg'),
 Operation('remux','Remux без перекодирования','Видео',V,'ffmpeg'),
 Operation('mute','Удалить звук','Видео',V,'ffmpeg'),
 Operation('replace_audio','Заменить аудиодорожку','Видео',('mp4','mkv','mov'),'ffmpeg'),
 Operation('merge_video','Объединить видео (одинаковые параметры)','Видео',('mp4','mkv','mov'),'ffmpeg',True),
 Operation('add_subtitle','Добавить субтитры','Видео',('mkv','mp4'),'ffmpeg'),
 Operation('remove_subtitle','Удалить субтитры','Видео',('mkv','mp4'),'ffmpeg'),
 Operation('extract_subtitle','Извлечь первую дорожку субтитров','Видео',('srt','ass','vtt'),'ffmpeg'),
 Operation('burn_subtitle','Встроить субтитры в изображение','Видео',('mp4','mkv'),'ffmpeg'),
 Operation('audio','Аудио / извлечь звук из видео','Аудио',A,'ffmpeg'),
 Operation('merge_audio','Объединить аудио','Аудио',A,'ffmpeg',True),
 Operation('image','Конвертировать / изменить изображение','Изображения',I,'pillow'),
 Operation('video_gif','Видео → GIF','Изображения',('gif',),'ffmpeg'),
 Operation('images_gif','Изображения → GIF','Изображения',('gif',),'pillow',True),
 Operation('emoji','GIF / видео → Animated Emoji','VRChat',('png',),'ffmpeg'),
 Operation('images_pdf','Изображения → PDF','PDF',('pdf',),'pillow',True),
 Operation('pdf_merge','Объединить PDF','PDF',('pdf',),'pypdf',True),
 Operation('pdf_pages','Извлечь / переставить / повернуть страницы','PDF',('pdf',),'pypdf'),
 Operation('pdf_compress','Оптимизировать PDF','PDF',('pdf',),'pypdf'),
 Operation('pdf_images','PDF → PNG в ZIP','PDF',('zip',),'pdfium'),
 Operation('archive','Создать архив','Архивы',('zip','tar','tar.gz','tar.bz2','tar.xz'),'stdlib',True),
 Operation('extract','Распаковать архив','Архивы',('folder',),'stdlib'),
 Operation('document','Конвертировать документ','Документы',('pdf','docx','odt','rtf','txt','html','xlsx','ods','pptx','odp'),'soffice'),
 Operation('ebook','Конвертировать книгу','Электронные книги',('epub','mobi','azw3','pdf','txt','htmlz'),'ebook-convert'),
]
REGISTRY = {o.id:o for o in OPERATIONS}
IMAGE_INPUTS = set(I) | {'jpeg','heic','heif','apng'}

def file_kind(path):
    """Recognize common formats by content, then use extensions for containers/media."""
    p=Path(path)
    ext=p.suffix.lower().lstrip('.')
    # Office documents and EPUB are ZIP containers, so their extensions win.
    if ext in {'docx','xlsx','pptx','odt','ods','odp','epub','mobi','azw3','htmlz'}:
        return 'ebook' if ext in {'epub','mobi','azw3','htmlz'} else 'document'
    try:
        with p.open('rb') as source: header=source.read(32)
    except OSError:
        header=b''
    if header.startswith(b'%PDF-'): return 'pdf'
    if header.startswith((b'\x89PNG\r\n\x1a\n',b'\xff\xd8\xff',b'GIF87a',b'GIF89a',b'BM',b'II*\x00',b'MM\x00*')): return 'image'
    if header.startswith(b'RIFF') and header[8:12]==b'WEBP': return 'image'
    if header.startswith((b'PK\x03\x04',b'PK\x05\x06')): return 'archive'
    if ext in IMAGE_INPUTS: return 'image'
    if ext in V: return 'video'
    if ext in A: return 'audio'
    if ext=='pdf': return 'pdf'
    if ext in {'zip','tar','gz','bz2','xz','7z'}: return 'archive'
    return 'document' if ext in {'doc','odt','rtf','txt','html','htm','xls','ods','ppt','odp'} else 'unknown'

def compatible_operations(paths):
    """Return only operations that can accept every selected input file."""
    if not paths: return OPERATIONS[:]
    kinds=[file_kind(path) for path in paths]
    common=set(kinds)
    supported={'archive'}
    if common=={'video'}:
        supported.update({'video','remux','mute','replace_audio','add_subtitle','remove_subtitle','extract_subtitle','burn_subtitle','audio','video_gif','emoji'})
        if len(paths)>1: supported.add('merge_video')
    elif common=={'audio'}:
        supported.add('audio')
        if len(paths)>1: supported.add('merge_audio')
    elif common=={'image'}:
        supported.update({'image','images_pdf'})
        if len(paths)>1: supported.add('images_gif')
        if len(paths)==1 and Path(paths[0]).suffix.lower()=='.gif': supported.add('emoji')
    elif common=={'pdf'}:
        supported.update({'pdf_pages','pdf_compress','pdf_images'})
        if len(paths)>1: supported.add('pdf_merge')
    elif common=={'archive'}:
        if len(paths)==1: supported.add('extract')
    elif common=={'document'}: supported.add('document')
    elif common=={'ebook'}: supported.add('ebook')
    return [op for op in OPERATIONS if op.id in supported]

def category(path):
    return {'image':'Изображения','audio':'Аудио','video':'Видео','pdf':'PDF','archive':'Архивы','ebook':'Электронные книги','document':'Документы','unknown':'Неизвестный файл'}[file_kind(path)]
