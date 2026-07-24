"""Unit tests for the subject-spotlight overlay helpers (pipeline/compose/gen_spotlight)."""
import numpy as np

from pipeline.compose.gen_spotlight import (
    build_overlay,
    dim_desaturate,
    resolve_subject,
)


def test_dim_desaturate_greys_and_darkens():
    # White collapses to a neutral grey at the dim level (luma of white is 1).
    white = np.ones((1, 1, 3), np.float32)
    out = dim_desaturate(white, dim=0.68, desat=0.35)
    assert np.allclose(out, 0.68, atol=1e-4)

    # A saturated red loses saturation (green/blue rise toward luma) and darkens.
    red = np.array([[[1.0, 0.0, 0.0]]], np.float32)
    r, g, b = dim_desaturate(red, dim=0.68, desat=0.35)[0, 0]
    assert r < 1.0 and g > 0.0 and abs(g - b) < 1e-6  # channels converge


def test_resolve_subject_keeps_seeded_island_drops_neighbour_and_unseeded():
    # Two separate landmasses in an ocean; the right one is a neighbour.
    dem_land = np.zeros((6, 6), bool)
    dem_land[1:5, 0:2] = True   # left island (the subject)
    dem_land[1:5, 4:6] = True   # right island (a neighbour)
    neighbours = np.zeros((6, 6), bool)
    neighbours[1:5, 4:6] = True
    seed = np.zeros((6, 6), bool)
    seed[2, 0] = True           # seeds the left island only

    subject = resolve_subject(dem_land, neighbours, seed)
    assert subject[1:5, 0:2].all()      # whole seeded island kept
    assert not subject[1:5, 4:6].any()  # neighbour dropped
    assert subject.sum() == 8


def test_resolve_subject_splits_a_shared_landmass_at_the_border():
    # One connected landmass spanning subject + neighbour (a land border, no sea
    # between): removing the neighbour's polygon must cut it at the border.
    dem_land = np.ones((4, 6), bool)          # all land, connected across the frame
    neighbours = np.zeros((4, 6), bool)
    neighbours[:, 3:] = True                   # right half belongs to a neighbour
    seed = np.zeros((4, 6), bool)
    seed[1, 1] = True                          # subject is the left half

    subject = resolve_subject(dem_land, neighbours, seed)
    assert subject[:, :3].all()
    assert not subject[:, 3:].any()


def test_resolve_subject_empty_when_seed_lands_on_removed_land():
    dem_land = np.ones((4, 4), bool)
    neighbours = np.ones((4, 4), bool)   # everything is a neighbour
    seed = np.zeros((4, 4), bool)
    seed[1, 1] = True
    assert not resolve_subject(dem_land, neighbours, seed).any()


def test_build_overlay_transparent_inside_opaque_dimmed_outside_untouched_margin():
    size = 24
    rgb = np.ones((size, size, 3), np.float32)          # bright white hero
    hero_alpha = np.ones((size, size), np.float32)
    hero_alpha[0, :] = 0.0                               # a transparent frame margin row
    subject = np.zeros((size, size), bool)
    subject[8:16, 8:16] = True                          # subject block in the centre

    overlay = build_overlay(rgb, hero_alpha, subject, dim=0.68, desat=0.35,
                            feather_px=1.0, outline_px=1.0)
    assert overlay.shape == (size, size, 4)

    # Deep inside the subject: transparent (the hero shows through).
    assert overlay[12, 12, 3] < 0.1
    # Deep outside, on content, clear of the outline band: opaque and dimmed.
    assert overlay[4, 4, 3] > 0.9
    assert overlay[4, 4, 0] < 0.9
    # The transparent margin row is left untouched (overlay adds nothing there).
    assert overlay[0, 4, 3] < 0.1
