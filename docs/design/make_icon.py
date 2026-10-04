# Tiles app icon generator: 2x2 asymmetric grid of rounded tiles (sun tile larger) on warm light bg.
import sys
from PIL import Image, ImageDraw, ImageFilter
OUT = sys.argv[1]
SS = 4  # supersample
BG = (0xF6, 0xF3, 0xEE)
SUN, CORAL, SKY, MINT = (0xFF,0xC8,0x3D), (0xFF,0x6B,0x5A), (0x3D,0xA5,0xFF), (0x2E,0xD3,0xA0)

def tiles_layer(size, span, shadow=True):
    """Transparent RGBA image of `size` px with the tile grid centred, total extent `span` px."""
    S = size * SS
    big, small = 0.585, 0.355           # column/row fractions; gap = remainder
    gap = 1 - big - small
    x0 = (S - span*SS) / 2
    u = span * SS
    a = x0; b = x0 + big*u; c = b + gap*u; d = x0 + u
    r_big, r_small = 0.17*big*u, 0.20*small*u
    rects = [((a,a,b,b), SUN, r_big), ((c,a,d,b), CORAL, r_small),
             ((a,c,b,d), SKY, r_small), ((c,c,d,d), MINT, r_small)]
    img = Image.new('RGBA', (S,S), (0,0,0,0))
    if shadow:
        sh = Image.new('RGBA', (S,S), (0,0,0,0)); sd = ImageDraw.Draw(sh)
        off = 0.018*u
        for (x1,y1,x2,y2), col, r in rects:
            sd.rounded_rectangle((x1, y1+off, x2, y2+off), r, fill=(90,60,30,46))
        sh = sh.filter(ImageFilter.GaussianBlur(0.03*u))
        img = Image.alpha_composite(img, sh)
    d = ImageDraw.Draw(img)
    for (x1,y1,x2,y2), col, r in rects:
        d.rounded_rectangle((x1,y1,x2,y2), r, fill=col+(255,))
    # subtle vertical sheen (lighter top -> none at bottom), clipped to tiles
    grad = Image.linear_gradient('L').resize((S,S)).point(lambda v: int((255-v)*0.13))
    hl = Image.new('RGBA', (S,S), (255,255,255,0))
    mask = Image.new('L', (S,S), 0); md = ImageDraw.Draw(mask)
    for (x1,y1,x2,y2), col, r in rects:
        md.rounded_rectangle((x1,y1,x2,y2), r, fill=255)
    from PIL import ImageChops
    hl.putalpha(ImageChops.multiply(grad, mask))
    img = Image.alpha_composite(img, hl)
    return img.resize((size,size), Image.LANCZOS)

def background(size):
    img = Image.new('RGB', (size,size), BG)
    # very soft warm vignette: lighter centre
    glow = Image.new('L', (size,size), 0); gd = ImageDraw.Draw(glow)
    gd.ellipse((size*0.1,size*0.05,size*0.9,size*0.85), fill=255)
    glow = glow.filter(ImageFilter.GaussianBlur(size*0.12))
    light = Image.new('RGB', (size,size), (0xFB,0xF9,0xF5))
    return Image.composite(light, img, glow).convert('RGBA')

fg = tiles_layer(1024, 580)
bg = background(1024)
fg.save(f'{OUT}/foreground.png'); bg.save(f'{OUT}/background.png')
full = Image.alpha_composite(bg, fg)
full.save(f'{OUT}/icon_full.png')
tiles_layer(288, 256, shadow=False).save(f'{OUT}/startIcon.png')
# preview: masked squircle at several sizes
prev = Image.new('RGBA', (1024+192+96+48+80, 1024), (255,255,255,255))
m = Image.new('L', (1024,1024), 0); ImageDraw.Draw(m).rounded_rectangle((0,0,1023,1023), 230, fill=255)
masked = Image.new('RGBA',(1024,1024),(0,0,0,0)); masked.paste(full,(0,0),m)
x=0
for s in (1024,192,96,48):
    prev.alpha_composite(masked.resize((s,s), Image.LANCZOS), (x, 0)); x += s+20
prev.save(f'{OUT}/preview.png')
