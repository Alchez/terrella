#!/usr/bin/env bash
# Blender-drift guard.
#
# The pipeline venv is Python 3.14, but five modules must ALSO import cleanly under
# Blender's bundled interpreter (3.13.9): palette.py (shared look constants, imported by
# both the tile shaders and the bpy scene), render_files.py and render_seam.py (the names a
# render directory's images go by and the declaration of which were written, both read by the
# rig, which is why they are stdlib-only), and scene_build.py / scene_dump.py (bpy scripts run
# inside Blender). This type-checks exactly those files at the 3.13 language level, so
# 3.14-only syntax or stdlib cannot silently enter a module Blender still has to load.
#
# Single source of truth for the Blender-shared file list — CI and local both call this
# script, so the list never drifts between the two. Add a file here when a new module
# becomes shared with Blender.
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run pyright --pythonversion 3.13 \
  pipeline/look/palette.py \
  pipeline/render_files.py \
  pipeline/render/render_seam.py \
  pipeline/render/scene_build.py \
  pipeline/render/scene_dump.py
