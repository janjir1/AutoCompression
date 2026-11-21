import json
import vapoursynth as vs

core = vs.core

# Passed in by compressor2.py through "vspipe -a":
#   source      - file to open
#   cache       - L-SMASH index file (.lwi)
#   options     - JSON dict with the vszip.Deband arguments (profile section "Deband")
#   crop_top    - even top crop in pixels (optional, default 0)
#   crop_bottom - even bottom crop in pixels (optional, default 0)
#   target_w    - target width for scaling before deband (optional, 0 = keep width)
opts = json.loads(options)
crop_t = int(globals().get("crop_top", 0))
crop_b = int(globals().get("crop_bottom", 0))
out_w = int(globals().get("target_w", 0))

clip = core.lsmas.LWLibavSource(source, cachefile=cache)

if (crop_t > 0 or crop_b > 0) and (crop_t + crop_b < clip.height):
    clip = core.std.Crop(clip, top=crop_t, bottom=crop_b)


def fmt(bits):
    return core.query_video_format(clip.format.color_family, vs.INTEGER, bits,
                                   clip.format.subsampling_w, clip.format.subsampling_h)


if out_w > 0 and out_w != clip.width:
    out_h = max(2, round(clip.height * out_w / clip.width / 2) * 2)
    clip = core.resize.Lanczos(clip, width=out_w, height=out_h, format=fmt(16))   # scale + 16 bit
else:
    clip = core.resize.Point(clip, format=fmt(16))                                # work in 16 bit

clip = core.vszip.Deband(clip, **opts)
clip = core.resize.Point(clip, format=fmt(10), dither_type="error_diffusion")     # 10 bit out
clip.set_output()