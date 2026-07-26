"""hero_variants: the srcset rung ladder and the quality policy recorded beside it.

Existence alone cannot decide whether a variant is current — a file re-encoded at q95 is
indistinguishable from the q85 one it replaced, so the `out.exists()` skip that made this module
idempotent would also make a quality change a no-op. hero_variants_recipe.json closes that, and
these pin the four properties that make it trustworthy: a missing recipe reads as the historical
q85 rather than as unknown, a rung whose policy moved is rewritten, a rung whose policy did not is
left alone, and the recipe is updated BEFORE the rewrite so an interrupted pass resumes instead of
deleting what it has already produced.

GDAL is stubbed throughout: this is about the staleness decision, not about WebP encoding.
"""

import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline.compose import hero_variants

NATIVE = 7680
ALL_RUNGS = (640, 960, 1280, 1920, 3840, 7680)
SLUGS = ("alpha", "beta")


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A fake hero store: two masters, both landscape at the native long edge, no GDAL."""
    heroes = tmp_path / "heroes"
    variants = tmp_path / "variants"
    heroes.mkdir()
    variants.mkdir()
    for slug in SLUGS:
        (heroes / f"{slug}.png").write_text("master")

    written: list[tuple[str, int, int]] = []
    recipe_seen: list[str] = []

    def fake_make_variant(src, wide, long_px, quality, out):
        written.append((src.stem, long_px, quality))
        recipe_seen.append(recipe.read_text() if recipe.exists() else "")
        out.write_text(f"webp q{quality}")

    recipe = variants / "hero_variants_recipe.json"
    monkeypatch.setattr(hero_variants, "HEROES", heroes)
    monkeypatch.setattr(hero_variants, "VARIANTS", variants)
    monkeypatch.setattr(hero_variants, "RECIPE", recipe)
    monkeypatch.setattr(hero_variants, "dims", lambda path: (NATIVE, 5738))
    monkeypatch.setattr(hero_variants, "make_variant", fake_make_variant)
    return SimpleNamespace(variants=variants, recipe=recipe, written=written,
                           recipe_seen=recipe_seen)


def run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["hero_variants.py", *argv])
    return hero_variants.main()


def legacy_variants(store, rungs):
    """Variants as the store held them before the recipe existed: written by a bare QUALITY = 85.

    The sentinel body is deliberately NOT what the stub encoder writes for q85. Making them equal
    would leave the byte-identity control unable to fail, which is how it first passed under a
    probe that rewrote every rung.
    """
    for slug in SLUGS:
        for rung in rungs:
            (store.variants / f"{slug}-{rung}.webp").write_text(f"pre-recipe {slug}-{rung}")


class TestPolicy:
    def test_quality_splits_at_the_large_rung(self):
        assert hero_variants.quality_for(640) == hero_variants.SMALL_QUALITY
        assert hero_variants.quality_for(1920) == hero_variants.SMALL_QUALITY
        assert hero_variants.quality_for(hero_variants.LARGE_RUNG_PX) == hero_variants.LARGE_QUALITY
        assert hero_variants.quality_for(7680) == hero_variants.LARGE_QUALITY

    def test_rungs_never_upscale_and_always_include_native(self):
        """A target at or above native collapses into the single native variant."""
        assert hero_variants.rungs_for(7680, 5738) == list(ALL_RUNGS)
        assert hero_variants.rungs_for(1000, 800) == [640, 960, 1000]
        assert hero_variants.rungs_for(500, 400) == [500]

    def test_the_ladder_matches_the_spotlight_overlay(self):
        """The gallery layers the overlay on the hero with one shared `sizes`, so a rung present in
        one ladder and absent from the other makes the browser pick mismatched files."""
        from pipeline.compose import gen_spotlight
        assert gen_spotlight.TARGETS == hero_variants.TARGETS


class TestFirstRun:
    def test_an_empty_store_writes_every_rung(self, store, monkeypatch):
        run(monkeypatch)
        assert len(store.written) == len(SLUGS) * len(ALL_RUNGS)
        assert {rung for _slug, rung, _quality in store.written} == set(ALL_RUNGS)

    def test_a_legacy_store_rewrites_only_the_rungs_whose_quality_moved(self, store, monkeypatch):
        """The load-bearing case. An absent recipe means "written at q85", so 1920 must be left
        alone while 3840 and native are re-encoded — and the three new rungs simply appear."""
        legacy_variants(store, (1920, 3840, 7680))
        run(monkeypatch)
        rewritten = {(rung, quality) for _slug, rung, quality in store.written}
        assert (1920, 85) not in rewritten
        assert (3840, 95) in rewritten
        assert (7680, 95) in rewritten
        assert {rung for rung, _quality in rewritten} == {640, 960, 1280, 3840, 7680}

    def test_a_legacy_store_leaves_the_untouched_rung_byte_identical(self, store, monkeypatch):
        """The control that stops the check above passing vacuously: 1920 is not merely absent from
        the written list, its file on disk is the original."""
        legacy_variants(store, (1920, 3840, 7680))
        untouched = store.variants / "alpha-1920.webp"
        before = untouched.read_text()
        run(monkeypatch)
        assert untouched.read_text() == before


class TestIdempotence:
    def test_a_second_run_writes_nothing(self, store, monkeypatch):
        run(monkeypatch)
        store.written.clear()
        run(monkeypatch)
        assert store.written == []

    def test_the_recipe_describes_every_rung_after_a_full_pass(self, store, monkeypatch):
        """Including the rungs that were skipped — the file documents the store, not just the delta."""
        run(monkeypatch)
        assert hero_variants.read_recipe() == {rung: hero_variants.quality_for(rung)
                                               for rung in ALL_RUNGS}

    def test_force_rewrites_a_current_store(self, store, monkeypatch):
        run(monkeypatch)
        store.written.clear()
        run(monkeypatch, "--force")
        assert len(store.written) == len(SLUGS) * len(ALL_RUNGS)


class TestResumability:
    def test_a_stale_rung_is_recorded_before_its_files_are_written(self, store, monkeypatch):
        """The ordering that makes an interrupted 2-hour pass resumable. If the recipe were written
        after the rewrite, a crash mid-rung would leave the rung still reading as stale and the next
        run would DELETE the q95 files it had already produced."""
        legacy_variants(store, (1920, 3840, 7680))
        run(monkeypatch)
        for (_slug, rung, _quality), recipe_at_call in zip(store.written, store.recipe_seen):
            if rung in (3840, 7680):
                assert f'"{rung}": 95' in recipe_at_call

    def test_an_interrupted_rewrite_resumes_instead_of_restarting(self, store, monkeypatch):
        """Simulates the crash: the recipe already says q95 and some files exist at q95. The next
        run must fill in only the missing ones."""
        legacy_variants(store, (1920, 3840, 7680))
        hero_variants.write_recipe({rung: hero_variants.quality_for(rung) for rung in ALL_RUNGS})
        (store.variants / "alpha-3840.webp").write_text("webp q95")
        run(monkeypatch)
        assert ("alpha", 3840, 95) not in store.written
        assert ("beta", 3840, 95) not in store.written   # present from legacy_variants, so skipped
        assert set(store.written) == {(slug, rung, 85)
                                      for slug in SLUGS for rung in (640, 960, 1280)}


class TestAtomicWrite:
    """`out.exists()` is this module's entire resume oracle, so a killed encode must not leave
    behind a file that looks finished.

    Found while checking whether a running pass could safely be restarted for a fan-out: it could
    not. gdal_translate wrote straight to the final name, so an interrupt at any point produced a
    truncated variant that every later run would skip — the same trap build_tiles documents for the
    tile cut, and the reason `--resume` was removed there. These exercise the real make_variant;
    the encoder stub the other tests use goes nowhere near this path.
    """

    def test_a_killed_encode_leaves_no_variant_behind(self, tmp_path, monkeypatch):
        out = tmp_path / "alpha-7680.webp"

        def dying_gdal(cmd, check):
            Path(cmd[-1]).write_text("half a webp")     # GDAL creates its target, then dies
            raise subprocess.CalledProcessError(1, cmd)

        monkeypatch.setattr(hero_variants.subprocess, "run", dying_gdal)
        with pytest.raises(subprocess.CalledProcessError):
            hero_variants.make_variant(tmp_path / "alpha.png", True, 7680, 95, out)
        assert not out.exists(), "a truncated encode would be skipped as done by every later run"

    def test_a_stale_staging_file_never_becomes_a_variant(self, tmp_path, monkeypatch):
        """The leftover from a previous kill must be overwritten, not adopted."""
        out = tmp_path / "alpha-7680.webp"
        (tmp_path / "alpha-7680.webp.tmp").write_text("wreckage from an earlier kill")

        def real_looking_gdal(cmd, check):
            Path(cmd[-1]).write_text("a whole webp")

        monkeypatch.setattr(hero_variants.subprocess, "run", real_looking_gdal)
        hero_variants.make_variant(tmp_path / "alpha.png", True, 7680, 95, out)
        assert out.read_text() == "a whole webp"

    def test_the_pam_sidecar_is_renamed_with_the_variant(self, tmp_path, monkeypatch):
        """GDAL emits <target>.aux.xml, so staging under a .tmp name would otherwise scatter
        `alpha-7680.webp.tmp.aux.xml` orphans through the store."""
        out = tmp_path / "alpha-7680.webp"

        def gdal_with_sidecar(cmd, check):
            target = Path(cmd[-1])
            target.write_text("a whole webp")
            target.with_name(target.name + ".aux.xml").write_text("<PAMDataset/>")

        monkeypatch.setattr(hero_variants.subprocess, "run", gdal_with_sidecar)
        hero_variants.make_variant(tmp_path / "alpha.png", True, 7680, 95, out)
        assert (tmp_path / "alpha-7680.webp.aux.xml").exists()
        assert list(tmp_path.glob("*.tmp*")) == []


class TestLadderServesTheLayout:
    """The guard for the defect that started all of this: the site declared a ~350 px card and the
    smallest rung that existed was 1920, so the browser fetched ~30x the pixels it drew — not
    because `sizes` was wrong, but because it had nothing smaller to pick. Nothing anywhere related
    what the pages ASK for to what the pipeline PRODUCES, in either direction.

    Covers EVERY ladder, keyed to the surfaces that actually layer it. The first version of this
    guard checked `hero_variants` alone and passed while the globe panel was still pulling an 85 kB
    1920 border onto a 48 kB 640 hero — a check over one of three ladders reads as coverage without
    being it, which is the same failure as the vacuous control above.

    Cross-language by necessity, and the same shape as test_scene_build_sync: the two ends of the
    contract live in different runtimes, so the pin has to read the file rather than import it.
    """
    # page -> the `sizes` constant it declares, and the ladders layered into that surface.
    PAGES = (
        ("index.astro", "SIZES", ("hero", "spotlight")),
        ("globe.astro", "sizesAttr", ("hero", "border")),
    )

    @staticmethod
    def ladders() -> dict[str, tuple[int, ...]]:
        """Every rung ladder the pipeline produces, by the name the surfaces know it as."""
        from pipeline.compose import gen_borders, gen_spotlight
        return {"hero": hero_variants.TARGETS,
                "spotlight": gen_spotlight.TARGETS,
                "border": gen_borders.TARGETS}

    def declarations(self):
        """(page, constant, [fixed CSS px], [ladder names]) for each `sizes` the site declares."""
        pages = Path(__file__).resolve().parents[1] / "web/src/pages"
        found = []
        for filename, constant, ladder_names in self.PAGES:
            source = (pages / filename).read_text()
            match = re.search(rf'const {constant} = "([^"]+)"', source)
            assert match, (f"{filename} no longer declares `const {constant} = \"...\"` — this "
                           f"guard reads the layout's own words, so a rename must fail here "
                           f"rather than silently stop checking anything")
            found.append((filename, constant,
                          [int(px) for px in re.findall(r"(\d+)px(?!\s*\))", match.group(1))],
                          ladder_names))
        return found

    def test_every_ladder_is_actually_checked(self):
        """Stops a ladder being added to the pipeline and quietly escaping this guard."""
        covered = {name for _f, _c, _w, names in self.declarations() for name in names}
        assert covered == set(self.ladders()), (
            f"ladders {set(self.ladders()) - covered} are produced but no surface claims them — "
            f"either wire them into PAGES or they are unreachable and should not be generated")

    @staticmethod
    def picked_rung(ladder: tuple[int, ...], needed_px: int) -> int:
        """What a browser fetches for `needed_px`: the smallest rung that covers it, or the largest
        there is when none does. A ladder is coarse by design, so rounding UP is correct — the
        defect is only ever how FAR up it has to round."""
        ascending = sorted(ladder)
        return next((rung for rung in ascending if rung >= needed_px), ascending[-1])

    def test_every_ladder_serves_its_surface_at_every_common_dpr(self):
        """Simulates selection rather than pinning rung numbers, so it stays true if either end
        moves. Two directions matter and they fail differently: rounding DOWN shows as blur, and
        rounding far up shows as bytes — 1920 for a 350 px card was 30x, which is what this catches.
        The 2x linear ceiling is one rung of slack, not a tuning knob.
        """
        ladders = self.ladders()
        for filename, constant, widths, ladder_names in self.declarations():
            assert widths, (
                f"{filename} {constant} declares no fixed CSS px. The gallery is masonry, so the "
                f"card is a near-constant column and a viewport fraction over-declares by up to "
                f"3.08x at 3440 — measured. A fixed width is the honest declaration")
            for ladder_name in ladder_names:
                ladder = ladders[ladder_name]
                for width in widths:
                    for device_pixel_ratio in (1, 2, 3):
                        needed = width * device_pixel_ratio
                        picked = self.picked_rung(ladder, needed)
                        assert picked >= needed, (
                            f"{filename} {constant} / {ladder_name}: {width} CSS px at DPR "
                            f"{device_pixel_ratio} needs {needed} device px and the ladder tops "
                            f"out at {picked} — this upscales")
                        assert picked / needed < 2, (
                            f"{filename} {constant} / {ladder_name}: {width} CSS px at DPR "
                            f"{device_pixel_ratio} needs {needed} device px but the next rung is "
                            f"{picked} — {picked / needed:.1f}x wider than the layout draws")


class TestSubsetRuns:
    def test_only_never_records_a_rung_it_did_not_finish(self, store, monkeypatch):
        """--only rewrites one slug's files, so recording the rung would claim the other slug moved
        too. It writes without recording; a later full run then redoes the rung, wastefully but
        never dishonestly."""
        legacy_variants(store, (1920, 3840, 7680))
        run(monkeypatch, "--only", "alpha")
        assert hero_variants.read_recipe() == {}
        assert {slug for slug, _rung, _quality in store.written} == {"alpha"}

    def test_an_unknown_slug_fails_loudly(self, store, monkeypatch):
        with pytest.raises(SystemExit):
            run(monkeypatch, "--only", "nowhere")
