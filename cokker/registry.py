from dataclasses import dataclass

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

def category(path):
    from pathlib import Path
    e = Path(path).suffix.lower().lstrip('.')
    if e in IMAGE_INPUTS: return 'Изображения'
    if e in A: return 'Аудио'
    if e in V: return 'Видео'
    if e == 'pdf': return 'PDF'
    if e in ('zip','tar','gz','bz2','xz','7z'): return 'Архивы'
    if e in ('epub','mobi','azw3'): return 'Электронные книги'
    return 'Документы'
