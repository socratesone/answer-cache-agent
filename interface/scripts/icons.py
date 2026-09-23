"""Original geometric q. application mark. Requires Pillow on the build machine only."""
from pathlib import Path
from PIL import Image, ImageDraw
root=Path(__file__).resolve().parents[1]/'public'
for size in (16,32,48,128):
    scale=4
    image=Image.new('RGBA',(size*scale,size*scale))
    draw=ImageDraw.Draw(image)
    def box(values): return tuple(round(v*size*scale) for v in values)
    draw.rounded_rectangle(box((0,0,1,1)),radius=int(size*scale*.23),fill='#245640')
    draw.ellipse(box((.22,.22,.7,.7)),fill='#ffffff')
    draw.ellipse(box((.34,.34,.58,.58)),fill='#245640')
    draw.rounded_rectangle(box((.56,.50,.70,.81)),radius=max(1,int(size*scale*.04)),fill='#ffffff')
    draw.ellipse(box((.76,.63,.85,.72)),fill='#ffffff')
    image.resize((size,size),Image.Resampling.LANCZOS).save(root/f'icon{size}.png')
