import tempfile, threading, subprocess, zipfile
from pathlib import Path
from PIL import Image
from pypdf import PdfReader
from cokker.engine import Engine
from cokker.models import Job, Options
from cokker.storage import Store, Presets

def convert(inputs,operation,fmt,out,**kwargs):
    job=Job([str(p) for p in inputs],operation,Options(format=fmt,**kwargs).__dict__,str(out))
    return Path(Engine(threading.Event()).convert(job)[0])

def test_image_pdf_archive():
    with tempfile.TemporaryDirectory() as tmp:
        d=Path(tmp); a=d/'оранжевый дракон.png'; b=d/'кадр_2.png'
        Image.new('RGBA',(128,96),(255,120,0,230)).save(a); Image.new('RGBA',(128,96),(20,130,200,255)).save(b)
        jpg=convert([a],'image','jpg',d,width=64,height=64,crop='10,10,80,70',rotate=90,flip='horizontal')
        with Image.open(jpg) as im:assert im.size==(56,64)
        webp=convert([a],'image','webp',d,target_mb=.004)
        assert webp.stat().st_size<=.004*1024*1024
        gif=convert([a,b],'images_gif','gif',d,frame_ms=120)
        with Image.open(gif) as im:assert im.n_frames==2
        pdf=convert([a,b],'images_pdf','pdf',d)
        assert len(PdfReader(pdf).pages)==2
        pages=convert([pdf],'pdf_pages','pdf',d,pages='2,1')
        assert len(PdfReader(pages).pages)==2
        pngs=convert([pdf],'pdf_images','zip',d)
        with zipfile.ZipFile(pngs) as z: assert len(z.namelist())==2
        zipped=convert([a,b],'archive','zip',d)
        extracted=convert([zipped],'extract','folder',d)
        assert (extracted/a.name).is_file()
        malicious=d/'malicious.zip'
        with zipfile.ZipFile(malicious,'w') as z:z.writestr('../outside.txt','bad')
        try:convert([malicious],'extract','folder',d)
        except ValueError:pass
        else:raise AssertionError('Archive traversal was not blocked')
        assert not (d/'outside.txt').exists()

def test_media():
    with tempfile.TemporaryDirectory() as tmp:
        d=Path(tmp); mp4=d/'input video.mp4';wav=d/'audio.wav'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=160x120:rate=30','-f','lavfi','-i','sine=frequency=450:sample_rate=44100','-t','2','-c:v','mpeg4','-c:a','aac','-shortest','-y',str(mp4)],check=True)
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=600:sample_rate=44100','-t','2','-y',str(wav)],check=True)
        out=convert([mp4],'video','mp4',d,start=.25,end=1.5,width=80,height=80,rotate=90,flip='horizontal',fps=15,speed=1.25)
        assert out.stat().st_size>1000
        mute=convert([mp4],'mute','mp4',d)
        assert mute.stat().st_size>1000
        audio=convert([mp4],'audio','mp3',d,start=.3,end=1.4)
        assert audio.stat().st_size>1000
        gif=convert([mp4],'video_gif','gif',d,start=.2,end=1.2)
        with Image.open(gif) as im:assert im.n_frames>1
        sheet=convert([mp4],'emoji','png',d,start=0,end=2,emoji_frames=16)
        with Image.open(sheet) as im:assert im.size==(1024,1024)
        merged=convert([mp4,mp4],'merge_video','mp4',d)
        assert merged.stat().st_size>mp4.stat().st_size
        merged_audio=convert([wav,wav],'merge_audio','mp3',d)
        assert merged_audio.stat().st_size>1000

def test_presets_recovery():
    with tempfile.TemporaryDirectory() as tmp:
        d=Path(tmp);s=Store(d);p=Presets(s)
        obj={'schemaVersion':1,'presetName':'Фото для сайта','category':'Изображения','operation':'image','parameters':{'format':'webp','quality':82,'width':1920}}
        p.save([obj]);path=d/'preset.json';p.export_file(path,p.all());p.import_file(path)
        assert len(p.all())==2
        j=Job(['A'],'image',{'format':'png'},str(d));s.save_job(j)
        assert s.jobs()[0].id==j.id
