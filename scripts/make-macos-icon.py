"""Convert the existing software icon into Apple's iconset (on the build Mac)."""
from pathlib import Path
import subprocess
import sys
from PIL import Image


def make_icon(source, output):
    output = Path(output)
    iconset = output.parent / 'ClinicalExtractor.iconset'
    iconset.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as source_image:
        image = source_image.convert('RGBA')
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                name = f'icon_{size}x{size}' + ('@2x' if scale == 2 else '') + '.png'
                image.resize((size*scale, size*scale), Image.Resampling.LANCZOS).save(iconset / name)
    subprocess.run(['/usr/bin/iconutil', '-c', 'icns', str(iconset), '-o', str(output)], check=True)


if __name__ == '__main__':
    make_icon(sys.argv[1], sys.argv[2])
