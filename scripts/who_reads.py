"""Which code names a file in the store, and whose output goes stale when that file changes.

    python -m scripts.who_reads data/raw/mars/sim3292/lapc_sim3292.json
    python -m scripts.who_reads --module pipeline/render/viking_luma.py   # silent if nothing
    python -m scripts.who_reads --index                 # every declared source, and every orphan

`--module` is the form `who-reads-this-module.py` injects on the first `Read` of a pipeline module,
which is the delivery this was built for: the cost of asking was never the barrier — remembering to
ask was — so the answer arrives unasked or not at all.

AN INSTRUMENT, NOT A GATE, on `scripts/prose_report.py`'s reasoning: it prints and returns 0.

WHY A GREP IS NOT THIS. A producer declares what it reads through a CALLABLE — see
`perennial_ice.CapIce.sources` for the argument — so that a redirected data root moves the
declaration with it. A callable is opaque to a text search: a `sources` function that builds its
tuple by calling a path accessor in a comprehension mentions no filename anywhere, and the producers
that restage on that file cannot be found by searching for it. This executes the declarations
instead, which is the only way to read them.

A DECLARED SOURCE IS A RESTAGE, which is what the second section is worth: `cap_is_fresh` and
`warp_needs_rebuild` both gate on the producer's own `sources()`, so a file listed there rebuilds
that producer's output on the next pass, and the report gives the line the declaration sits on.

WHAT IT CANNOT ANSWER, stated because a lookup that quietly covers half its subject is worse than
none — and printed as COUNTS on every run, so believe the report over this paragraph.

- A path is found only through a constant, an accessor this is willing to call, or a declaration.
  Functions that take an argument or are not named as accessors are never invoked, so a file reached
  only that way is visible here only where some producer declares it.
- NO FRESHNESS IS TRACED. Registry declarations are one way a file is watched; a stage gating itself
  on a recipe or a digest is another, and this reads none of those. So "no producer declares it" is
  strictly narrower than "nothing rebuilds when it changes", and the modules owning a predicate of
  their own are counted rather than followed.
- Two modules import `bpy` and cannot load outside Blender's interpreter. Neither names a store path
  today, which is a fact about today and is why they are reported rather than assumed away.
"""

import argparse
import ast
import importlib
import inspect
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "pipeline"


@dataclass(frozen=True)
class Naming:
    """One binding in the source that names `path`."""

    path: Path
    where: str
    #: Bound at import, so a redirected `MAPS_DATA` does NOT move it — the failure `paths.py`'s
    #: module docstring forbids in prose and nothing enforces. Reported per row because the answer
    #: to "who names this file" is different under a relocated store, and only for these rows.
    frozen: bool


@dataclass(frozen=True)
class Declaration:
    """One producer that has declared `path` among its sources — i.e. one output that restages."""

    path: Path
    producer: str
    #: `module:lineno` of the `sources` callable itself, since half of them are lambdas and
    #: `__name__` says `<lambda>` for every one of those.
    declared_at: str


@dataclass(frozen=True)
class Coverage:
    """What the run could not reach, carried alongside the answer rather than printed and lost."""

    unimportable: list[tuple[str, str]]
    #: `(where, why)` for every function that returns a Path and was NOT called. Sized rather than
    #: described: an instrument that states its blind spot in prose invites the reader to assume it
    #: is small, and this one is not.
    uncalled: list[tuple[str, str]]
    #: Modules owning a freshness predicate of their own, which this reads NOT AT ALL. A registry
    #: declaration is one way a file is watched and stages gate by recipe or digest besides, so
    #: "no producer declares it" is a narrower claim than "nothing rebuilds when it changes".
    private_gates: list[str]


def load_package() -> tuple[list[ModuleType], list[tuple[str, str]]]:
    """Import every module under `pipeline/`, returning what loaded and what did not.

    Failures are returned rather than swallowed: the two `bpy` modules can only load inside
    Blender's own interpreter, and a silent skip would let this report "nothing names that file"
    about a module it never opened.
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    loaded: list[ModuleType] = []
    failed: list[tuple[str, str]] = []
    for source in sorted(ROOT.glob(f"{PACKAGE}/**/*.py")):
        stem = source.relative_to(ROOT).with_suffix("")
        parts = stem.parts[:-1] if stem.name == "__init__" else stem.parts
        name = ".".join(parts)
        try:
            loaded.append(importlib.import_module(name))
        except Exception as exc:  # noqa: BLE001 — reported, never suppressed
            failed.append((name, f"{type(exc).__name__}: {exc}"))
    return loaded, failed


def _module_body(module: ModuleType) -> list[ast.stmt]:
    """The module's top-level statements, or nothing when it has no readable source on disk."""
    origin = getattr(module, "__file__", None)
    if origin is None:
        return []
    return ast.parse(Path(origin).read_text(encoding="utf-8")).body


def constants(module: ModuleType) -> list[Naming]:
    """Module-level bindings holding a `Path`, taken from the module's own source.

    The AST rather than `vars()`, because `vars()` cannot separate a definition from a re-export:
    `paths.DATA` is bound across most of the package, and attributing the store root to thirty
    modules buries the one that owns it.
    """
    found: list[Naming] = []
    for statement in _module_body(module):
        targets = (statement.targets if isinstance(statement, ast.Assign)
                   else [statement.target] if isinstance(statement, ast.AnnAssign) else [])
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            value = getattr(module, target.id, None)
            if isinstance(value, Path):
                found.append(Naming(value, f"{module.__name__}.{target.id}", frozen=True))
    return found


#: A function is called only if its NAME says accessor as well as its annotation. Two independent
#: signals rather than one, because the annotation alone is satisfied by `write_unit`, `_write_cap`
#: and `render_cap_north` — producers that return the path they just wrote. Every one of those is
#: excluded today by needing an argument, which is luck and not a property, and the cost of being
#: too strict here is a row in NOT ANSWERED while the cost of being too loose is a write.
ACCESSOR_SUFFIXES = ("_path", "_dir", "_root")


def accessors(module: ModuleType) -> tuple[list[Naming], list[tuple[str, str]]]:
    """Module-level functions that return a path and can be called for it; and every one that can't.

    The second half is not an afterthought — it is this instrument's blind spot, returned so the
    report can count it. A path reached ONLY through an uncalled function is invisible here unless
    some producer declares it.
    """
    found: list[Naming] = []
    uncalled: list[tuple[str, str]] = []
    for statement in _module_body(module):
        if not isinstance(statement, ast.FunctionDef) or not _returns_path(statement):
            continue
        function = getattr(module, statement.name, None)
        where = f"{module.__name__}.{statement.name}()"
        if not callable(function):
            uncalled.append((where, "not callable on the imported module"))
        elif not statement.name.endswith(ACCESSOR_SUFFIXES):
            uncalled.append((where, "not named as an accessor"))
        elif _needs_an_argument(function):
            uncalled.append((where, "takes an argument"))
        else:
            found.extend(_called(function, where, uncalled))
    return found, uncalled


def _called(function: Any, where: str, uncalled: list[tuple[str, str]]) -> list[Naming]:
    """Call one accessor, recording a failure in `uncalled` rather than raising out of the run."""
    try:
        value = function()
    except Exception as exc:  # noqa: BLE001 — an accessor that cannot answer is itself a finding
        uncalled.append((where, f"raised {type(exc).__name__}: {exc}"))
        return []
    return [Naming(value, where, frozen=False)] if isinstance(value, Path) else []


#: What a stage calls the predicate it gates itself on. One name, several policies — content digest,
#: recipe sidecar, recipe plus mtimes, bare existence — which is exactly why this script reads none
#: of them and reports their owners instead.
GATE_NAME = "is_fresh"


def private_gate(module: ModuleType) -> str | None:
    """This module's own freshness predicate, if it has one."""
    owned = any(isinstance(statement, ast.FunctionDef) and statement.name == GATE_NAME
                for statement in _module_body(module))
    return module.__name__ if owned else None


def _returns_path(statement: ast.FunctionDef) -> bool:
    """Whether the definition annotates its return as a `Path`, by name."""
    returns = statement.returns
    return isinstance(returns, ast.Name) and returns.id == "Path"


def _needs_an_argument(function: Any) -> bool:
    """Whether calling `function` with no arguments would fail."""
    try:
        inspect.signature(function).bind()
    except TypeError:
        return True
    return False


def declarations(modules: list[ModuleType]) -> list[Declaration]:
    """Every producer in the package that declares its sources as a zero-argument callable.

    Found BY SHAPE and not by name — any module-level dict whose values carry a callable `sources`
    taking no argument. A third body's registry is answered without editing this, which is the same
    reason the two that exist are written alike.
    """
    found: list[Declaration] = []
    for module in modules:
        for statement in _module_body(module):
            targets = (statement.targets if isinstance(statement, ast.Assign)
                       else [statement.target] if isinstance(statement, ast.AnnAssign) else [])
            for target in targets:
                if not isinstance(target, ast.Name):
                    continue
                registry = getattr(module, target.id, None)
                if not isinstance(registry, dict):
                    continue
                for key, producer in registry.items():  # pyright: ignore[reportUnknownVariableType]
                    found.extend(_sources_of(module, target.id, key, producer))
    return found


def _sources_of(module: ModuleType, registry: str, key: Any, producer: Any) -> list[Declaration]:
    """The paths one registry entry declares, or nothing when it is not a producer at all."""
    supply = getattr(producer, "sources", None)
    if not callable(supply) or _needs_an_argument(supply):
        return []
    declared = supply()
    if not isinstance(declared, Iterable):
        return []
    where = f"{module.__name__}.{registry}[{key!r}]"
    return [Declaration(entry, where, _defined_at(supply))
            for entry in declared if isinstance(entry, Path)]


def _defined_at(function: Any) -> str:
    """`module.py:lineno` for a callable — the only useful identity a lambda has.

    Shortened against the checkout only when it IS under the checkout: `relative_to` raises rather
    than declining, so a module loaded from anywhere else ends a whole run in a formatting helper.
    """
    try:
        source = inspect.getsourcefile(function)
        _, line = inspect.getsourcelines(function)
    except (OSError, TypeError):
        return "?"
    if source is None:
        return f"?:{line}"
    absolute = Path(source)
    stem = absolute.relative_to(ROOT) if absolute.is_relative_to(ROOT) else absolute
    return f"{stem}:{line}"


def covers(named: Path, target: Path) -> bool:
    """Whether a change to `target` is a change to `named` — the same file, or one inside the other.

    BOTH DIRECTIONS, AND ONLY FOR DECLARATIONS. A declared source may be a DIRECTORY:
    `freshness.newest_mtime` recurses into one, so a chunk beneath a VRT's directory moves that
    producer's gate exactly as the directory does.
    """
    return named == target or target.is_relative_to(named) or named.is_relative_to(target)


def names(naming: Naming, target: Path) -> bool:
    """Whether `naming` points at `target` or at something inside it.

    THE ANCESTOR DIRECTION IS DELIBERATELY ABSENT, which is what separates this from `covers`. Every
    path in the store sits under `paths.DATA` and a dozen re-derived roots, so admitting ancestors
    answers "who names this file" with fifteen rows that would be identical for any file at all —
    true, useless, and printed above the row that is not. `inside` reports the nearest of them.
    """
    return naming.path == target or naming.path.is_relative_to(target)


def inside(namings: list[Naming], target: Path) -> list[Naming]:
    """The DEEPEST bindings strictly containing `target`, for orientation — whose area is it in?

    ONE ROW PER PATH, not per binding. A root is re-derived under its own name in module after
    module, so a file with no closer container is otherwise announced seven times over by seven
    spellings of `DATA` — which is the noise `names` exists to keep out of the section above.
    """
    containing = [naming for naming in namings
                  if naming.path != target and target.is_relative_to(naming.path)]
    if not containing:
        return []
    deepest = max(len(naming.path.parts) for naming in containing)
    by_path: dict[Path, Naming] = {}
    for naming in sorted(containing, key=lambda found: found.where):
        if len(naming.path.parts) == deepest:
            by_path.setdefault(naming.path, naming)
    return list(by_path.values())


def _print_coverage(coverage: Coverage, listed: bool) -> None:
    """What this run could not see. Printed on every answer, including the empty ones.

    `listed` because the same block serves both views and they want different lengths: naming forty
    functions under a one-path lookup is the noise that gets a report skipped, and a report skipped
    is a report that no longer covers anything.
    """
    print("\nNOT ANSWERED")
    for name, reason in coverage.unimportable:
        print(f"  did not import  {name} — {reason}")
    print(f"  {len(coverage.uncalled)} functions return a path and were not called, so a file named"
          " only through one is found here only where a producer declares it")
    if listed:
        for where, reason in sorted(coverage.uncalled):
            print(f"      {where:<58} {reason}")
    print(f"  {len(coverage.private_gates)} modules own a freshness predicate this does not read, so"
          " a file no producer declares may still be gated by its own stage")
    if listed:
        for where in sorted(coverage.private_gates):
            print(f"      {where}.{GATE_NAME}()")


def answer(target: Path, namings: list[Naming], declared: list[Declaration],
           coverage: Coverage) -> None:
    """Print who names `target` and what restages when it moves."""
    print(f"{target}\n")
    hits = [naming for naming in namings if names(naming, target)]
    print("NAMED BY")
    for naming in sorted(hits, key=lambda found: found.where):
        binding = "frozen at import" if naming.frozen else "read at call time"
        print(f"  {naming.where:<62} {binding}")
    if not hits:
        print("  nothing — no constant holds it and no callable accessor returns it")
    for naming in sorted(inside(namings, target), key=lambda found: found.where):
        print(f"  (inside {naming.where})")

    restaged = [entry for entry in declared if covers(entry.path, target)]
    print("\nDECLARED AS A SOURCE OF — these restage when it changes")
    for entry in sorted(restaged, key=lambda found: found.producer):
        print(f"  {entry.producer:<62} {entry.declared_at}")
    if not restaged:
        print("  no producer declares it — see NOT ANSWERED before reading that as 'nothing"
              " rebuilds'")
    if not hits and not restaged and not target.exists():
        print("\n  ...AND IT IS NOT ON DISK. A misspelt path reads exactly like a real orphan here,"
              "\n  so check the spelling before believing either line above.")
    _print_coverage(coverage, listed=False)


def module_name(source: Path) -> str | None:
    """The dotted name of a file inside the package, or None when it is outside it."""
    absolute = source.resolve()
    if not absolute.is_relative_to(ROOT):
        return None
    stem = absolute.relative_to(ROOT).with_suffix("")
    parts = stem.parts[:-1] if stem.name == "__init__" else stem.parts
    return ".".join(parts) if parts and parts[0] == PACKAGE else None


def store_root() -> Path:
    """The store this run describes — `MAPS_DATA` when set, resolved exactly as `paths` resolves it.

    Asked of `paths` rather than assumed to be `<repo>/data`, since a redirected root is the whole
    reason the declarations are callables and it would be odd for their reader to hardcode it.
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    return importlib.import_module(f"{PACKAGE}.paths").DATA


def _under_data(path: Path) -> str:
    """`path` written against the store root where it is under it — the store's own vocabulary."""
    root = store_root()
    return str(path.relative_to(root)) if path.is_relative_to(root) else str(path)


def is_a_root(path: Path) -> bool:
    """Whether `path` is the store root or something containing it, rather than a place in it.

    A root COVERS every declared source there is, so expanding its producers answers any module
    with the same eight rows — the same noise `names` keeps out of the path lookup, arriving here
    through the one constant per module that re-derives the checkout.
    """
    return store_root().is_relative_to(path)


def module_view(name: str, namings: list[Naming], declared: list[Declaration],
                gates: list[str]) -> None:
    """What one module says about the store: the paths it names, and what restages behind each.

    SILENT WHEN THERE IS NOTHING TO SAY, on `history-lookup.py`'s reasoning and for its reason — a
    signal that fires on every module trains the eye to skip the one module where it mattered. Most
    of the package names no store path at all, so most of the package prints nothing here.
    """
    owned = [naming for naming in namings if naming.where.startswith(f"{name}.")]
    declares = [entry for entry in declared if entry.producer.startswith(f"{name}.")]
    gate = name in gates
    if not owned and not declares and not gate:
        return

    # By PRODUCER and not by declaration: a directory covers several of its own files, and one
    # producer named once per file it declares inside that directory reads as several producers.
    restaged = {naming.where: [] if is_a_root(naming.path) else
                sorted({entry.producer for entry in declared if covers(entry.path, naming.path)})
                for naming in owned}
    print(name)
    for naming in sorted(owned, key=lambda found: found.where):
        root = is_a_root(naming.path)
        binding = ("a re-derived root" if root
                   else "frozen at import" if naming.frozen else "read at call time")
        # Whole, not shortened: a root abbreviated against itself prints as `.`, and the one row
        # whose point is WHICH root this module re-derived is the one that must not be abbreviated.
        location = naming.path if root else _under_data(naming.path)
        print(f"  {naming.where.removeprefix(f'{name}.'):<34} {location}   [{binding}]")
        if root:
            continue
        for producer in restaged[naming.where]:
            print(f"      restages  {producer.removeprefix(f'{PACKAGE}.')}")
        # Only where the module has SOME declared path, so a module with none says so once rather
        # than once per row — nine identical lines is the shape a reader learns to skip.
        if not restaged[naming.where] and any(restaged.values()):
            print("      no producer declares it")
    if owned and not any(restaged.values()):
        print("  no producer declares any of these")
    if declares:
        print(f"  DECLARES {len(declares)} source(s) of its own producers:")
        for entry in sorted(declares, key=lambda found: (found.producer, found.path)):
            print(f"      {_under_data(entry.path):<52} "
                  f"{entry.producer.removeprefix(f'{name}.')}")
    if gate:
        print(f"  OWNS {GATE_NAME}() — it gates itself, by a policy this does not read")


def index(namings: list[Naming], declared: list[Declaration], coverage: Coverage) -> None:
    """The whole table: every declared source with its producers, then every named orphan.

    The orphan half is the one worth reading. A path a module names and no producer declares is a
    file whose change restages nothing, which is either dead weight or a gate with a hole in it, and
    the two look identical from inside the module that names it.
    """
    by_path: dict[Path, list[Declaration]] = {}
    for entry in declared:
        by_path.setdefault(entry.path, []).append(entry)
    print(f"DECLARED SOURCES — {len(by_path)} paths, {len(declared)} declarations")
    for path in sorted(by_path):
        print(f"  {path}")
        for entry in sorted(by_path[path], key=lambda found: found.producer):
            print(f"      {entry.producer:<58} {entry.declared_at}")

    orphans = [naming for naming in namings
               if not any(covers(naming.path, entry.path) for entry in declared)]
    print(f"\nNAMED, DECLARED BY NO PRODUCER — {len(orphans)}")
    for naming in sorted(orphans, key=lambda found: found.where):
        binding = "frozen" if naming.frozen else "call-time"
        print(f"  {naming.where:<62} {binding}")
    _print_coverage(coverage, listed=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", help="a path in the store; need not exist")
    parser.add_argument("--index", action="store_true", help="every declared source and orphan")
    parser.add_argument("--module", metavar="FILE",
                        help="what one pipeline module says about the store; silent if nothing")
    options = parser.parse_args()
    if not options.target and not options.index and not options.module:
        parser.error("give a path, --module FILE, or --index")

    name = module_name(Path(options.module)) if options.module else None
    if options.module and name is None:
        return 0

    modules, unimportable = load_package()
    namings: list[Naming] = []
    uncalled: list[tuple[str, str]] = []
    gates: list[str] = []
    for module in modules:
        namings.extend(constants(module))
        called, skipped = accessors(module)
        namings.extend(called)
        uncalled.extend(skipped)
        gates.extend(filter(None, [private_gate(module)]))
    coverage = Coverage(unimportable, uncalled, gates)
    declared = declarations(modules)

    if name is not None:
        module_view(name, namings, declared, gates)
    elif options.index:
        index(namings, declared, coverage)
    else:
        answer(Path(options.target).resolve(), namings, declared, coverage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
