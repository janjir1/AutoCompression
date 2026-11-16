import json
import vapoursynth as vs

core = vs.core

# Passed in by compressor2.py through "vspipe -a":
#   source  - file to open
#   cache   - L-SMASH index file (.lwi)
#   options - JSON dict with the vszip.Deband arguments (profile section "Deband")
opts = json.loads(options)

clip = core.lsmas.LWLibavSource(source, cachefile=cache)


def fmt(bits):
    return core.query_video_format(clip.format.color_family, vs.INTEGER, bits,
                                   clip.format.subsampling_w, clip.format.subsampling_h)


clip = core.resize.Point(clip, format=fmt(16))                                    # work in 16 bit
clip = core.vszip.Deband(clip, **opts)
clip = core.resize.Point(clip, format=fmt(10), dither_type="error_diffusion")     # 10 bit out
clip.set_output()
