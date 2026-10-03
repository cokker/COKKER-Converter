import io, json, math, os, shutil, tempfile, zipfile, tarfile, time, logging
from pathlib import Path
from PIL import Image, ImageOps, ImageSequence
from .models import Options
from .registry import REGISTRY
from .platform_services import executable, ProcessRunner, Cancelled, keep_awake
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError: pass

LOG=logging.getLogger('conversion')

class Engine:
    def __init__(self,cancel=None,progress=None):
        self.runner=ProcessRunner(cancel); self.progress=progress or (lambda value:None)
    def check_cancel(self):
        if self.runner.cancel.is_set(): raise Cancelled('Отменено')
    def probe(self,path):
        tool=executable('ffprobe')
        if not tool: raise RuntimeError('Не найден ffprobe. Установите FFmpeg в разделе «Компоненты».')
        return json.loads(self.runner.run([tool,'-v','error','-show_format','-show_streams','-of','json',path]))
    def convert(self,job):
        o=Options(**job.options); o.validate(); op=REGISTRY[job.operation]
        if o.format not in op.formats: raise ValueError('Формат не поддерживается этой операцией.')
        paths=[Path(p).resolve() for p in job.inputs]
        if not paths or any(not p.is_file() for p in paths): raise ValueError('Исходный файл отсутствует.')
        outdir=Path(job.output_dir).resolve(); outdir.mkdir(parents=True,exist_ok=True)
        before=sum(p.stat().st_size for p in paths)
        if shutil.disk_usage(outdir).free < max(16*1024*1024,int(before*1.2)):
            raise RuntimeError('Недостаточно свободного места для безопасной обработки.')
        stem=paths[0].stem[:90]+'_'+job.operation
        if job.operation=='emoji': stem+=f'_{o.emoji_frames}frames_{o.fps or 15:g}fps'
        suffix='.'+o.format if o.format!='folder' else ''
        out=outdir/(stem+suffix); n=1
        while out.exists(): out=outdir/(stem+f'_{n}'+suffix); n+=1
        tempdir=Path(tempfile.mkdtemp(prefix='.cokker-',dir=outdir))
        temp=tempdir/('result'+suffix)
        started=time.monotonic()
        try:
            self.check_cancel()
            if op.backend=='ffmpeg': self.media(paths,temp,job.operation,o,tempdir)
            elif op.backend=='pillow': self.images(paths,temp,job.operation,o)
            elif op.backend in ('pypdf','pdfium'): self.pdf(paths,temp,job.operation,o)
            elif op.backend=='stdlib': self.archives(paths,temp,job.operation,o)
            else: self.external(paths[0],temp,job.operation,o,tempdir)
            self.check_cancel()
            if not temp.exists() or (temp.is_file() and not temp.stat().st_size): raise RuntimeError('Компонент не создал корректный результат.')
            if temp.is_file():
                if op.backend=='ffmpeg' and o.format not in ('srt','ass','vtt'): self.probe(temp)
                elif o.format in ('png','jpg','webp','gif','tiff','avif','bmp','ico'):
                    with Image.open(temp) as im: im.verify()
                elif o.format=='pdf':
                    from pypdf import PdfReader
                    if not len(PdfReader(temp).pages): raise RuntimeError('Получен пустой PDF.')
                elif o.format=='zip':
                    with zipfile.ZipFile(temp) as z:
                        if z.testzip(): raise RuntimeError('Архив повреждён.')
            # Link within the same volume publishes a fully written file atomically.
            if temp.is_dir():
                if out.exists(): raise FileExistsError('Папка результата уже существует.')
                temp.rename(out)
            else:
                try:
                    os.link(temp,out)
                except FileExistsError: raise RuntimeError('Имя результата занято. Повторите задачу.')
                except OSError as error: raise RuntimeError('Не удалось сохранить результат атомарно: '+str(error)) from error
                temp.unlink()
            self.progress(1)
            return str(out),before,(out.stat().st_size if out.is_file() else sum(p.stat().st_size for p in out.rglob('*') if p.is_file())),time.monotonic()-started
        finally: shutil.rmtree(tempdir,ignore_errors=True)
    def transformed(self,im,o):
        im=ImageOps.exif_transpose(im).convert('RGBA')
        if o.crop:
            x,y,w,h=map(int,o.crop.split(','))
            if x+w>im.width or y+h>im.height: raise ValueError('Рамка Crop выходит за границы изображения.')
            im=im.crop((x,y,x+w,y+h))
        if o.rotate: im=im.rotate(-o.rotate,expand=True)
        if o.flip=='horizontal': im=ImageOps.mirror(im)
        if o.flip=='vertical': im=ImageOps.flip(im)
        if o.width or o.height:
            w=o.width or round(im.width*o.height/im.height); h=o.height or round(im.height*o.width/im.width)
            if o.no_upscale: w=min(w,im.width); h=min(h,im.height)
            if o.scale_mode=='stretch': im=im.resize((w,h),Image.Resampling.LANCZOS)
            elif o.scale_mode=='fill': im=ImageOps.fit(im,(w,h),Image.Resampling.LANCZOS)
            else: im.thumbnail((w,h),Image.Resampling.LANCZOS)
        return im
    def images(self,paths,out,operation,o):
        if operation in ('images_gif','images_pdf'):
            frames=[]
            try:
                for i,p in enumerate(paths):
                    self.check_cancel()
                    with Image.open(p) as im: frame=self.transformed(im,o)
                    if frames: frame=ImageOps.pad(frame,frames[0].size,color=(0,0,0,0))
                    frames.append(frame); self.progress((i+1)/len(paths)*.7)
                if operation=='images_pdf':
                    rgb=[self.rgb(f) for f in frames]
                    rgb[0].save(out,'PDF',save_all=True,append_images=rgb[1:])
                else:
                    delays=[int(v) for v in o.frame_delays.split(',')] if o.frame_delays else [o.frame_ms]*len(frames)
                    if len(delays)!=len(frames): raise ValueError('Укажите одну длительность на каждый кадр.')
                    frames[0].save(out,'GIF',save_all=True,append_images=frames[1:],duration=delays,loop=o.loop,disposal=2)
            finally:
                for f in frames: f.close()
            return
        with Image.open(paths[0]) as original:
            if getattr(original,'n_frames',1)>1: raise ValueError('Для анимации используйте «Видео → GIF» или VRChat; преобразование в статичную картинку отключено во избежание потери кадров.')
            metadata={}
            if not o.strip_metadata:
                metadata={k:original.info[k] for k in ('exif','icc_profile') if k in original.info}
            im=self.transformed(original,o)
        fmt={'jpg':'JPEG','tiff':'TIFF'}.get(o.format,o.format.upper())
        if fmt in ('JPEG','BMP'): im=self.rgb(im)
        def encode(q):
            buf=io.BytesIO(); im.save(buf,fmt,quality=q,optimize=True,**metadata); return buf.getvalue()
        result=encode(o.quality)
        if o.target_mb:
            cap=int(o.target_mb*1024*1024)
            for step in range(32):
                self.check_cancel()
                if len(result)<=cap: break
                q=max(20,o.quality-step*6)
                if q==20 or fmt not in ('JPEG','WEBP','AVIF'):
                    if min(im.size)<=16: break
                    im=im.resize((max(1,int(im.width*.85)),max(1,int(im.height*.85))),Image.Resampling.LANCZOS)
                result=encode(q)
            if len(result)>cap: raise RuntimeError('Не удалось достичь заданного размера. Увеличьте лимит.')
        out.write_bytes(result)
    @staticmethod
    def rgb(im):
        bg=Image.new('RGB',im.size,'white'); bg.paste(im,mask=im.getchannel('A') if im.mode=='RGBA' else None); return bg
    def filters(self,o):
        vf=[]
        if o.crop:
            x,y,w,h=map(int,o.crop.split(',')); vf.append(f'crop={w}:{h}:{x}:{y}')
        if o.rotate==90: vf.append('transpose=1')
        elif o.rotate==270: vf.append('transpose=2')
        elif o.rotate==180: vf+=['hflip','vflip']
        if o.flip=='horizontal': vf+=['hflip']
        if o.flip=='vertical': vf+=['vflip']
        if o.width or o.height:
            w=str(o.width) if o.width else '-2'; h=str(o.height) if o.height else '-2'
            if o.no_upscale:
                if o.width: w=f"min(iw,{o.width})"
                if o.height: h=f"min(ih,{o.height})"
            if o.width and o.height and o.scale_mode!='stretch':
                mode='increase' if o.scale_mode=='fill' else 'decrease'
                vf.append(f"scale=w='{w}':h='{h}':force_original_aspect_ratio={mode}:force_divisible_by=2")
                if o.scale_mode=='fill': vf.append(f"crop=w='min(iw,{o.width})':h='min(ih,{o.height})'")
            else: vf.append(f"scale=w='{w}':h='{h}'")
        if o.fps: vf.append(f'fps={o.fps}')
        if o.speed!=1: vf.append(f'setpts=PTS/{o.speed}')
        af=[]; speed=o.speed
        while speed>2: af.append('atempo=2'); speed/=2
        while speed<.5: af.append('atempo=0.5'); speed/=.5
        if speed!=1: af.append(f'atempo={speed}')
        if o.normalize: af.append('loudnorm=I=-16:TP=-1.5:LRA=11')
        if o.volume!=1: af.append(f'volume={o.volume}')
        return vf,af
    def media(self,paths,out,operation,o,tempdir):
        ff=executable('ffmpeg')
        if not ff: raise RuntimeError('FFmpeg не найден. Добавьте его через «Настройки → Компоненты».')
        info=self.probe(paths[0]); streams=info.get('streams',[])
        has_video=any(s['codec_type']=='video' for s in streams); has_audio=any(s['codec_type']=='audio' for s in streams)
        duration=float(info.get('format',{}).get('duration',0) or 0)
        if o.start>=duration and duration: raise ValueError('Начало находится за концом файла.')
        if o.end and duration and o.end>duration+.05: raise ValueError('Конец находится за длительностью файла.')
        result_duration=((o.end or duration)-o.start)/o.speed
        vf,af=self.filters(o)
        common=[ff,'-hide_banner','-loglevel','error','-nostdin','-y']
        inp=['-i',str(paths[0])]
        if operation in ('replace_audio','add_subtitle','burn_subtitle'):
            if not Path(o.extra_file).is_file(): raise ValueError('Выберите дополнительный аудиофайл или субтитры.')
            if operation!='burn_subtitle': inp+=['-i',o.extra_file]
        if operation=='merge_video':
            allinfo=[info]+[self.probe(p) for p in paths[1:]]
            def signature(i):
                return [(s.get('codec_type'),s.get('codec_name'),s.get('width'),s.get('height'),s.get('sample_rate'),s.get('channels'),s.get('pix_fmt'),s.get('r_frame_rate'),s.get('time_base')) for s in i['streams']]
            if any(signature(i)!=signature(info) for i in allinfo): raise ValueError('Параметры видео отличаются. Сначала конвертируйте их в одинаковый формат и разрешение.')
            # Use safe generated names instead of embedding untrusted paths into concat syntax.
            names=[]
            for i,p in enumerate(paths):
                target=tempdir/f'part{i}{p.suffix}'
                try: os.link(p,target)
                except OSError: shutil.copyfile(p,target)
                names.append(f"file '{target.name}'")
            listing=tempdir/'concat.txt'; listing.write_text('\n'.join(names),encoding='utf-8')
            inp=['-f','concat','-safe','0','-i',str(listing)]
            result_duration=sum(float(i['format'].get('duration',0)) for i in allinfo)
        args=common+inp
        if o.start: args+=['-ss',str(o.start)]
        if o.end: args+=['-t',str((o.end-o.start)/o.speed)]
        if o.strip_metadata: args+=['-map_metadata','-1']
        if operation=='emoji':
            grid=int(math.sqrt(o.emoji_frames)); cell=1024//grid
            available=(o.end or duration)-o.start
            if available<=0: raise ValueError('Не удалось определить длительность анимации.')
            vf=[f for f in vf if not f.startswith('fps=')]
            vf += [f'fps={o.emoji_frames/available}',f'scale={cell}:{cell}:force_original_aspect_ratio=decrease',f'pad={cell}:{cell}:(ow-iw)/2:(oh-ih)/2:color=0x00000000',f'tile={grid}x{grid}:nb_frames={o.emoji_frames}']
            args+=['-vf',','.join(vf),'-frames:v','1','-an']
        elif operation=='video_gif':
            vf+=[] if o.fps else ['fps=15']
            vf+=[] if o.width or o.height else ['scale=480:-1']
            chain=','.join(vf)
            args+=['-filter_complex',f'[0:v]{chain},split[a][b];[a]palettegen=reserve_transparent=1[p];[b][p]paletteuse','-an','-loop',str(o.loop)]
        elif operation in ('remux','merge_video','mute','remove_subtitle','add_subtitle','replace_audio','extract_subtitle'):
            if vf or af or o.target_mb: raise ValueError('Эта операция копирует дорожки. Для Crop, скорости, FPS и размера выберите обычную конвертацию.')
            if operation=='extract_subtitle': args+=['-map','0:s:0','-c:s',{'srt':'srt','ass':'ass','vtt':'webvtt'}[o.format]]
            elif operation=='replace_audio': args+=['-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a',f'{o.audio_bitrate}k','-shortest']
            elif operation=='add_subtitle': args+=['-map','0:v?','-map','0:a?','-map','1:s:0','-c','copy','-c:s','mov_text' if o.format=='mp4' else 'srt']
            else:
                args+=['-map','0:v?']
                if operation!='mute': args+=['-map','0:a?']
                if operation in ('remux','merge_video') and o.format=='mkv': args+=['-map','0:s?']
                args+=['-c','copy']
        elif operation in ('audio','merge_audio'):
            if not has_audio: raise ValueError('В файле нет аудиодорожки.')
            if operation=='merge_audio':
                args=common
                for p in paths: args+=['-i',str(p)]
                tags=''.join(f'[{i}:a:0]' for i in range(len(paths)))
                chain=f'{tags}concat=n={len(paths)}:v=0:a=1'
                if af: chain+=','+','.join(af)
                args+=['-filter_complex',chain+'[out]','-map','[out]']
                result_duration=sum(float(self.probe(p)['format'].get('duration',0)) for p in paths)/o.speed
            else:
                args+=['-map','0:a:0','-vn']
                if af: args+=['-af',','.join(af)]
            args+=self.audio_codec(o)
        else:
            if not has_video: raise ValueError('В файле нет видеодорожки.')
            if operation=='burn_subtitle':
                local=tempdir/('subtitle'+Path(o.extra_file).suffix); shutil.copyfile(o.extra_file,local)
                vf.append(f'subtitles={local.name}')
            vf.append('scale=trunc(iw/2)*2:trunc(ih/2)*2')
            args+=['-map','0:v:0','-map','0:a:0?','-vf',','.join(vf)]
            if af and has_audio: args+=['-af',','.join(af)]
            codec=o.codec if o.codec!='auto' else {'webm':'libvpx-vp9','ogv':'libtheora','wmv':'wmv2','mpeg':'mpeg2video','mpg':'mpeg2video','avi':'mpeg4','3gp':'mpeg4','flv':'flv'}.get(o.format,'libx264')
            if codec not in ('libx264','libx265','libaom-av1','libvpx-vp9','libtheora','wmv2','mpeg2video','mpeg4','flv'): raise ValueError('Неизвестный кодек.')
            enc=codec
            if o.hardware!='cpu' and codec in ('libx264','libx265'):
                suffix={'auto':'nvenc','nvenc':'nvenc','amf':'amf','qsv':'qsv'}[o.hardware]
                enc=('h264' if codec=='libx264' else 'hevc')+'_'+suffix
            args+=['-c:v',enc,'-pix_fmt','yuv420p']
            if o.target_mb:
                rate=int(o.target_mb*1024*1024*8*.95/max(result_duration,.01)-(o.audio_bitrate*1000 if has_audio else 0))
                if rate<32000: raise ValueError('Лимит слишком мал для длительности. Увеличьте его.')
                args+=['-b:v',str(rate)]
            elif enc in ('libx264','libx265','libvpx-vp9','libaom-av1'): args+=['-crf',str(round(40-o.quality*.28))]
            elif enc.endswith('nvenc'): args+=['-cq',str(round(40-o.quality*.28))]
            else: args+=['-b:v','3000k']
            if has_audio: args+=['-c:a',{'webm':'libopus','ogv':'libvorbis','wmv':'wmav2','mpeg':'mp2','mpg':'mp2'}.get(o.format,'aac'),'-b:a',f'{o.audio_bitrate}k']
            if o.format in ('mp4','mov','m4v'): args+=['-movflags','+faststart']
        args+=['-progress','pipe:1','-threads','2',str(out)]
        try: self.runner.run(args,self.progress,result_duration,cwd=tempdir)
        except RuntimeError:
            if operation in ('video','burn_subtitle') and o.hardware!='cpu' and enc!=codec:
                LOG.info('GPU encoder unavailable; falling back to CPU')
                i=args.index('-c:v')+1; args[i]=codec
                if '-cq' in args: args[args.index('-cq')]='-crf'
                self.runner.run(args,self.progress,result_duration,cwd=tempdir)
            else: raise
    @staticmethod
    def audio_codec(o):
        codec={'mp3':'libmp3lame','wav':'pcm_s16le','flac':'flac','aac':'aac','m4a':'aac','ogg':'libvorbis','opus':'libopus','wma':'wmav2','aiff':'pcm_s16be','ac3':'ac3'}[o.format]
        args=['-c:a',codec]
        if o.format not in ('wav','flac','aiff'): args+=['-b:a',f'{o.audio_bitrate}k']
        if o.sample_rate: args+=['-ar',str(o.sample_rate)]
        if o.channels: args+=['-ac',str(o.channels)]
        return args
    def pdf(self,paths,out,operation,o):
        from pypdf import PdfReader,PdfWriter
        if operation=='pdf_images':
            import pypdfium2 as pdfium
            with pdfium.PdfDocument(str(paths[0])) as doc,zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
                for i in range(len(doc)):
                    self.check_cancel(); page=doc[i]; bitmap=page.render(scale=2); im=bitmap.to_pil(); buf=io.BytesIO(); im.save(buf,'PNG')
                    z.writestr(f'page_{i+1:04}.png',buf.getvalue()); bitmap.close(); page.close(); self.progress((i+1)/len(doc))
            return
        writer=PdfWriter()
        for p in paths:
            self.check_cancel(); reader=PdfReader(p)
            if reader.is_encrypted: raise ValueError('PDF защищён паролем. Сначала откройте его в PDF-редакторе.')
            indexes=list(range(len(reader.pages)))
            if operation=='pdf_pages' and o.pages:
                indexes=[]
                for segment in o.pages.split(','):
                    bounds=segment.strip().split('-')
                    if len(bounds)==1: indexes.append(int(bounds[0])-1)
                    elif len(bounds)==2: indexes.extend(range(int(bounds[0])-1,int(bounds[1])))
                    else: raise ValueError('Страницы: например 1,3,5-8.')
                if not indexes or any(i<0 or i>=len(reader.pages) for i in indexes): raise ValueError('Страница вне диапазона.')
            for i in indexes:
                self.check_cancel(); page=writer.add_page(reader.pages[i])
                if o.rotate: page.rotate(o.rotate)
                if operation=='pdf_compress': page.compress_content_streams()
        if o.strip_metadata: writer.metadata=None
        with open(out,'wb') as f: writer.write(f)
        writer.close()
    def archives(self,paths,out,operation,o):
        if operation=='extract':
            out.mkdir()
            def safe(name):
                p=(out/name).resolve()
                if not p.is_relative_to(out.resolve()) or ':' in name or '\\' in name: raise ValueError('Архив содержит небезопасный путь.')
                return p
            if zipfile.is_zipfile(paths[0]):
                with zipfile.ZipFile(paths[0]) as z:
                    total=sum(i.file_size for i in z.infolist())
                    if total>shutil.disk_usage(out).free*.8: raise ValueError('Недостаточно места для распаковки.')
                    for i,member in enumerate(z.infolist()):
                        self.check_cancel(); target=safe(member.filename)
                        if member.is_dir(): target.mkdir(parents=True,exist_ok=True)
                        else:
                            if (member.external_attr>>16)&0o170000==0o120000: raise ValueError('Ссылки внутри архива не поддерживаются.')
                            target.parent.mkdir(parents=True,exist_ok=True)
                            with z.open(member) as src,open(target,'xb') as dst:
                                while chunk:=src.read(1024*1024): self.check_cancel(); dst.write(chunk)
                        self.progress((i+1)/max(len(z.infolist()),1))
            else:
                with tarfile.open(paths[0]) as tar:
                    members=tar.getmembers()
                    if sum(m.size for m in members)>shutil.disk_usage(out).free*.8: raise ValueError('Недостаточно места для распаковки.')
                    for i,m in enumerate(members):
                        self.check_cancel(); target=safe(m.name)
                        if m.isdir(): target.mkdir(parents=True,exist_ok=True)
                        elif m.isfile():
                            target.parent.mkdir(parents=True,exist_ok=True)
                            with tar.extractfile(m) as src,open(target,'xb') as dst:
                                while chunk:=src.read(1024*1024): self.check_cancel(); dst.write(chunk)
                        else: raise ValueError('Ссылки и специальные файлы не поддерживаются.')
                        self.progress((i+1)/max(len(members),1))
            return
        names=set()
        def name(p):
            n=p.name; i=1
            while n in names: n=f'{p.stem}_{i}{p.suffix}'; i+=1
            names.add(n); return n
        if o.format=='zip':
            with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
                for i,p in enumerate(paths): self.check_cancel(); z.write(p,name(p)); self.progress((i+1)/len(paths))
        else:
            mode={'tar':'w','tar.gz':'w:gz','tar.bz2':'w:bz2','tar.xz':'w:xz'}[o.format]
            with tarfile.open(out,mode) as tar:
                for i,p in enumerate(paths): self.check_cancel(); tar.add(p,arcname=name(p)); self.progress((i+1)/len(paths))
    def external(self,path,out,operation,o,tempdir):
        tool=executable('soffice' if operation=='document' else 'ebook-convert')
        if not tool: raise RuntimeError('Установите LibreOffice или Calibre в разделе «Компоненты».')
        if operation=='ebook': self.runner.run([tool,path,out])
        else:
            profile=(tempdir/'lo-profile').as_uri()
            folder=tempdir/'converted'; folder.mkdir()
            self.runner.run([tool,f'-env:UserInstallation={profile}','--headless','--convert-to',o.format,'--outdir',folder,path])
            result=folder/(path.stem+'.'+o.format)
            if not result.is_file(): raise RuntimeError('LibreOffice не поддерживает такое преобразование документа.')
            shutil.move(result,out)
