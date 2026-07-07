"""Rewire Base Color to an intermediate node output and render a tiny frame.
Usage: blender -b FILE --python probe_tap.py -- TAP OUTPNG
TAP: searange | searamp | landramp | mask | full"""
import sys

import bpy

tap, outpng = sys.argv[sys.argv.index("--") + 1:]

s = bpy.context.scene
s.render.resolution_x, s.render.resolution_y = 512, 527
s.cycles.samples = 64
s.cycles.use_denoising = False
s.render.filepath = outpng

mat = bpy.data.objects["Plane"].active_material
nt = mat.node_tree
nodes = {}
for n in nt.nodes:
    nodes[n.label or n.name] = n
bsdf = nodes["Principled BSDF"]

TAPS = {
    "searange": ("Sea", "Result"),
    "searamp": ("Color Ramp", "Color"),
    "landramp": ("Color Ramp.001", "Color"),
    "mask": ("Image Texture.001", "Color"),
    "full": None,
}
if TAPS[tap]:
    node_name, sock = TAPS[tap]
    src = nodes[node_name].outputs[sock]
    dst = bsdf.inputs["Base Color"]
    for l in list(nt.links):
        if l.to_socket == dst:
            nt.links.remove(l)
    nt.links.new(src, dst)

bpy.ops.render.render(write_still=True)
print(f"probe {tap} -> {outpng}", flush=True)
