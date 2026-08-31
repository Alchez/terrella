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
from typing import ClassVar

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
        one ladder and absent from the other makes the browser pick mismatched files.

        COMPARING THE TUPLES IS NOT ENOUGH, and was briefly the whole test. The portrait fill rung is
        computed per hero from its aspect, so two modules can hold identical `TARGETS` and still
        disagree about what a portrait country gets — the tuple check passes while the overlay is
        missing exactly the rung this work added. The ladder is a FUNCTION now, so the pin has to be
        on the function.
        """
        from pipeline.compose import gen_spotlight
        assert gen_spotlight.TARGETS == hero_variants.TARGETS
        assert gen_spotlight.rungs_for is hero_variants.rungs_for, (
            "gen_spotlight must IMPORT rungs_for rather than restate the ladder — a copy cannot "
            "track an aspect-dependent rung")
        portrait = (round(NATIVE * 0.465), NATIVE)   # Albania: needs a fill rung
        assert hero_variants.fill_rung(*portrait) in hero_variants.rungs_for(*portrait)


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
    # surface -> the `sizes` constant it declares, and the ladders layered into that surface. Paths
    # are relative to `web/src/`, because NEITHER surface is a page any more: the globe's panel moved
    # out of `pages/earth/index.astro` so a second body could draw the same globe, and the gallery
    # moved out of `pages/index.astro` so Earth's lite route could render it at a second URL. Both
    # times a lookup rooted at `pages/` would have gone on reading a file that still existed.
    PAGES = (
        ("components/Gallery.astro", "SIZES", ("hero", "spotlight")),
    )

    #: Ladders still produced that NO surface draws, with the reason each is still generated.
    #: Named here rather than dropped from `ladders()`: an orphan costs render time and storage,
    #: and dropping it would make this file pass by having nothing left to compare.
    ORPHANED_LADDERS: ClassVar[dict[str, str]] = {
        "border": (
            "The globe's detail card was its last consumer and is now text-only; `.hp-border`, "
            "which the mobile exemption above still describes, had already stopped existing. "
            "gen_borders writes 1,010 PNGs nothing draws. Whether to keep writing them is a "
            "product call, carried in FUTURE."
        ),
    }

    # The viewports the `vw` arm of `sizes` actually serves, as (CSS px, device pixel ratio).
    # This guard used to read ONLY the fixed-px arm — its regex skips `640px` inside `(max-width:
    # 640px)` and kept just `440` — so the entire mobile branch, which is where the defect was,
    # was never evaluated. Six comfortable cells reported coverage of a ladder that was failing.
    MOBILE_VIEWPORTS = (
        (412, 1.75),   # Moto G Power — the Lighthouse mobile preset, and the LOWEST DPR here
        (360, 2.0),    # a cheap Android
        (412, 2.625),  # Pixel 7
        (390, 3.0),    # iPhone 15
        (430, 3.0),    # iPhone 15 Pro Max — the widest real mobile demand
    )

    # Aspect ratios the atlas actually contains, as width/height of the native render. The ladder is
    # keyed to the LONG EDGE while `srcset` selects on WIDTH, so for anything portrait the two are
    # not the same number and a guard that conflates them is testing landscape only. 0.234 is
    # Maldives, the narrowest; 1.0 and above stand in for every landscape country, where long edge
    # IS width and the distinction collapses.
    ASPECTS = (0.234, 0.307, 0.401, 0.465, 0.530, 0.603, 0.770, 1.0, 1.302, 1.659)

    # Aspects for which no rung below the q95 floor can cover mobile demand — a fill rung there
    # would arrive at inspection quality for a thumbnail, so they wait for the width-keyed ladder.
    # Named rather than silently skipped: an exemption that is not written down is a hole.
    UNSERVEABLE_ASPECTS = (0.234, 0.307)

    # Ladders the mobile contract does NOT yet hold, each with its reason. `test_every_exemption_is
    # _load_bearing` asserts each one would FAIL without the exemption, so the day a gap is closed
    # this list fails loudly rather than quietly covering nothing — the failure mode of every
    # skip-list ever written.
    MOBILE_EXEMPT_LADDERS: ClassVar[dict[str, str]] = {
        "border": (
            "gen_borders tops out at 1920, so a portrait border jumps straight to the country's "
            "native rung — a lossless PNG at ~3x the width the panel draws. It is off the cold "
            "path: `.hp-border` is display:none unless the visitor turns Borders on, and a lazy "
            "image with no layout box is never fetched. Closed by the width-keyed ladder in FUTURE."
        ),
    }

    @staticmethod
    def ladders() -> dict[str, tuple[int, ...]]:
        """Every rung ladder the pipeline produces, by the name the surfaces know it as."""
        from pipeline.compose import gen_borders, gen_spotlight
        return {"hero": hero_variants.TARGETS,
                "spotlight": gen_spotlight.TARGETS,
                "border": gen_borders.TARGETS}

    def declarations(self):
        """(page, constant, [fixed CSS px], [ladder names]) for each `sizes` the site declares."""
        source_root = Path(__file__).resolve().parents[1] / "web/src"
        found = []
        for filename, constant, ladder_names in self.PAGES:
            source = (source_root / filename).read_text()
            match = re.search(rf'const {constant} = "([^"]+)"', source)
            assert match, (f"{filename} no longer declares `const {constant} = \"...\"` — this "
                           f"guard reads the layout's own words, so a rename must fail here "
                           f"rather than silently stop checking anything")
            declaration = match.group(1)
            found.append((filename, constant,
                          [int(px) for px in re.findall(r"(\d+)px(?!\s*\))", declaration)],
                          ladder_names, declaration))
        return found

    def test_every_ladder_is_actually_checked(self):
        """Stops a ladder being added to the pipeline and quietly escaping this guard."""
        covered = {name for _f, _c, _w, names, _d in self.declarations() for name in names}
        assert covered.isdisjoint(self.ORPHANED_LADDERS), (
            f"{covered & set(self.ORPHANED_LADDERS)} is drawn by a surface again — delete its "
            f"ORPHANED_LADDERS entry, since the reason recorded there is now false")
        assert covered == set(self.ladders()) - set(self.ORPHANED_LADDERS), (
            f"ladders {set(self.ladders()) - covered - set(self.ORPHANED_LADDERS)} are produced "
            f"but no surface claims them — either wire them into PAGES, record why they are "
            f"orphaned, or they are unreachable and should not be generated")

    @staticmethod
    def picked_rung(ladder: tuple[int, ...], needed_px: int, aspect: float = 1.0) -> int:
        """What a browser fetches for `needed_px` of WIDTH: the smallest rung whose delivered width
        covers it, or the largest there is when none does. A ladder is coarse by design, so rounding
        UP is correct — the defect is only ever how FAR up it has to round.

        `aspect` is width/height of the native render, and it is the correction this guard was
        missing. A rung names the LONG EDGE, so for a portrait hero the delivered width is
        `rung * aspect` — Albania's 1920 rung is 892 px wide, not 1920. Comparing the rung number
        straight against needed pixels silently models every country as landscape, which is exactly
        how a 2x width gap at DPR 3 sat under a passing test.
        """
        ascending = sorted(ladder)
        delivered = min(1.0, aspect)
        return next((rung for rung in ascending if rung * delivered >= needed_px), ascending[-1])

    @staticmethod
    def delivered_width(rung: int, aspect: float) -> float:
        return rung * min(1.0, aspect)

    @staticmethod
    def ladder_at(ladder_name: str, aspect: float, ladders: dict[str, tuple[int, ...]]):
        """The rungs a country of this aspect actually gets.

        For hero and spotlight this calls the pipeline's OWN `rungs_for`, because the portrait fill
        rung is computed per hero and a copied tuple could not represent it — the guard would model
        a ladder nobody produces. The two share one function by import, so asking either is asking
        both. Everything else has a fixed ladder and is read as a tuple.
        """
        if ladder_name not in ("hero", "spotlight"):
            return ladders[ladder_name]
        native = 7680
        width, height = (round(native * aspect), native) if aspect < 1 else (native, round(native / aspect))
        return tuple(hero_variants.rungs_for(width, height))

    def test_every_ladder_serves_its_surface_at_every_common_dpr(self):
        """Simulates selection rather than pinning rung numbers, so it stays true if either end
        moves. Two directions matter and they fail differently: rounding DOWN shows as blur, and
        rounding far up shows as bytes — 1920 for a 350 px card was 30x, which is what this catches.
        The 2x linear ceiling is one rung of slack, not a tuning knob.
        """
        ladders = self.ladders()
        for filename, constant, widths, ladder_names, _declaration in self.declarations():
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

    @staticmethod
    def viewport_fractions(declaration: str) -> list[float]:
        """The `vw` fractions in a `sizes` declaration, as fractions of the viewport.

        The fixed-px arm serves desktop, where the gallery is masonry and a card is a near-constant
        column. The `vw` arm serves the single-column mobile layout — a DIFFERENT band, and the one
        the ladder was never checked against.
        """
        return [int(value) / 100 for value in re.findall(r"(\d+)vw", declaration)]

    def test_the_vw_arm_of_sizes_is_declared_and_therefore_checkable(self):
        """The guard reads the layout's own words, so a `sizes` that stops declaring a mobile arm
        must fail here rather than silently reduce this suite to the desktop case again."""
        for filename, constant, _widths, _ladders, declaration in self.declarations():
            assert self.viewport_fractions(declaration), (
                f"{filename} {constant} declares no `vw` arm. Below the single-column breakpoint a "
                f"card IS a viewport fraction, and dropping that arm would leave this guard "
                f"checking desktop only — which is how the portrait rung gap shipped")

    def test_every_ladder_serves_a_PORTRAIT_country_on_a_real_phone(self):
        """The mobile half of the ladder contract, which the desktop-only guard above cannot see.

        Two directions, and they fail differently: under-delivering shows as blur, over-delivering
        shows as bytes. The bytes direction is the one that bit — a portrait hero on a DPR-3 phone
        was landing two rungs up AND across the q85/q95 boundary, 399 KiB becoming 2,252 KiB.

        The 2x ceiling is one rung of slack, the same as the desktop case, and not a tuning knob.
        """
        ladders = self.ladders()
        for filename, constant, _widths, ladder_names, declaration in self.declarations():
            for fraction in self.viewport_fractions(declaration):
                for ladder_name in ladder_names:
                    if ladder_name in self.MOBILE_EXEMPT_LADDERS:
                        continue
                    for aspect in self.ASPECTS:
                        if aspect in self.UNSERVEABLE_ASPECTS:
                            continue
                        ladder = self.ladder_at(ladder_name, aspect, ladders)
                        for viewport, device_pixel_ratio in self.MOBILE_VIEWPORTS:
                            needed = round(viewport * fraction * device_pixel_ratio)
                            picked = self.picked_rung(ladder, needed, aspect)
                            got = self.delivered_width(picked, aspect)
                            assert got >= needed, (
                                f"{filename} {constant} / {ladder_name}: aspect {aspect} at "
                                f"{viewport} CSS px x DPR {device_pixel_ratio} needs {needed} px of "
                                f"width, and the top rung {picked} delivers only {got:.0f} — upscales")
                            assert got / needed < 2, (
                                f"{filename} {constant} / {ladder_name}: aspect {aspect} at "
                                f"{viewport} CSS px x DPR {device_pixel_ratio} needs {needed} px of "
                                f"width but rung {picked} delivers {got:.0f} — {got / needed:.1f}x "
                                f"the layout, and a portrait hero crossing 3840 also crosses q85->q95")
                            if ladder_name == "hero":
                                # THE INVARIANT THAT WAS ACTUALLY BROKEN, and the reason the width
                                # ceiling above is not enough on its own: at aspect 0.465 the 3840
                                # rung is only 1.50x too wide, comfortably inside one rung of slack
                                # — but 3840 is also where `quality_for` steps q85 -> q95, so the
                                # pixel jump and the quality jump compound and 399 KiB becomes
                                # 2,252 KiB. A card in a gallery is a thumbnail by definition; it
                                # must never select the rung reserved for a surface being zoomed in
                                # to. The bytes hid inside an acceptable-looking width ratio.
                                assert picked < hero_variants.LARGE_RUNG_PX, (
                                    f"{filename} {constant}: aspect {aspect} at {viewport} CSS px x "
                                    f"DPR {device_pixel_ratio} selects rung {picked}, which is at or "
                                    f"above the q{hero_variants.LARGE_QUALITY} inspection floor "
                                    f"({hero_variants.LARGE_RUNG_PX}) — inspection quality for a "
                                    f"thumbnail {got:.0f} px wide")

    def test_every_exemption_is_load_bearing(self):
        """An exemption that no longer exempts anything is a hole with a comment over it.

        Same reasoning as the vacuous-control problem this class already documents: a skip-list is
        the easiest place for coverage to quietly disappear, so each entry has to earn its place by
        still being a real failure. When a gap is closed, this fails and the entry gets deleted.
        """
        ladders = self.ladders()
        for ladder_name, reason in self.MOBILE_EXEMPT_LADDERS.items():
            assert ladder_name in ladders, f"exemption names {ladder_name!r}, which is not a ladder"
            assert reason.strip(), f"{ladder_name} is exempt with no reason recorded"
            ladder = ladders[ladder_name]
            failures = [
                (aspect, viewport, dpr)
                for aspect in self.ASPECTS if aspect not in self.UNSERVEABLE_ASPECTS
                for viewport, dpr in self.MOBILE_VIEWPORTS
                if self.delivered_width(
                    self.picked_rung(ladder, round(viewport * 0.92 * dpr), aspect), aspect
                ) < round(viewport * 0.92 * dpr)
            ]
            assert failures, (
                f"{ladder_name} is on the exemption list but now SERVES every mobile case — the "
                f"gap it was exempted for is closed, so delete the entry and let the guard cover it")


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
