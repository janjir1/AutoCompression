from PIL import Image

file = r"C:\Soubory\AutoCompression\Tests\blackbarDetection\wh92r1llb3q01.jpg"

im = Image.open(file, 'r')
pix = im.load()
print(im.size)
black_top = 0
black_bottom = 0


for i in range(0, im.size[1], 1):
    if (pix[im.size[0]/2, i] == (0, 0, 0)):
        black_top += 1
    else:
        break

for i in range(im.size[1]-1, -1, -1):
    if (pix[im.size[0]/2, i] == (0, 0, 0)):
        black_bottom += 1
    else:
        break

print(black_top)
print(black_bottom)

