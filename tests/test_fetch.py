"""The pipeline's HTTP identity, and the scan that keeps it from being bypassed.

WHY THIS FILE EXISTS AT ALL. Every acquisition in this pipeline used `urllib.request` directly and
therefore sent `User-Agent: Python-urllib/3.x`, which bot-protection edges block outright. It was
found the only way it could be found — by a download failing with HTTP 403 — because a mocked test
asserts whatever the mock was told to return, and every one of these acquisitions is mocked. So the
guard here cannot be "does `preflight` work": it has to be a structural claim about the whole
package, checkable offline, that no module has its own way out to the network.

THE SCAN FORBIDS THE MODULE, NOT THE FUNCTION, AND THAT IS THE WHOLE DESIGN. The first hand-grep for
this defect looked for `urlopen` and `urllib.request.Request` and reported nine call sites. There
were ten: `download_rgi` used `urlretrieve`, a spelling the grep never considered. A scan that names
functions can only ever be blind to the next function; a scan that names the IMPORT cannot, because
every spelling — `urlopen`, `urlretrieve`, `Request`, `build_opener`, whatever arrives next — has to
come through the same door.
"""

import ast
import inspect
import urllib.request
from pathlib import Path

import pytest

from pipeline import fetch, paths

#: The one module allowed to reach `urllib.request`, because it is the thing being funnelled through.
FETCH_MODULE = paths.ROOT / "pipeline/fetch.py"


def pipeline_sources() -> list[Path]:
    """Every Python module in the pipeline package except the fetch module itself."""
    return sorted(
        source for source in (paths.ROOT / "pipeline").rglob("*.py")
        if source != FETCH_MODULE and "__pycache__" not in source.parts
    )


def imports_urllib_request(source: Path) -> bool:
    """True if this module imports `urllib.request` in any spelling.

    Parsed rather than grepped: a docstring that mentions the module by name is prose and must not
    fail the gate, and `# type: ignore`-style trailing text must not hide a real import.
    """
    tree = ast.parse(source.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "urllib.request" for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module == "urllib.request":
            return True
    return False


def test_the_scan_reaches_the_whole_package_rather_than_a_handful_of_files():
    """Anti-vacuity: a scan over an empty list passes every assertion it makes.

    The number is a FLOOR rather than a pin — a rotting exact count would be refreshed rather than
    investigated, which is the failure mode a count in a test always has. What must never happen is
    the glob quietly matching nothing because the package moved.
    """
    sources = pipeline_sources()
    assert len(sources) > 30, f"the pipeline scan found only {len(sources)} modules"
    assert FETCH_MODULE.is_file(), "the fetch module is the scan's one exemption and must exist"
    assert FETCH_MODULE not in sources

    # THE HALF A COUNT CANNOT DO. A scan narrowed to skip the acquisition package would still be
    # over thirty modules and would still report clean forever, because clean code is clean under
    # any subset — a shrunken scope is only visible against a scope stated independently. Derived
    # from the package rather than listed, so a new acquirer is covered the day it is written.
    acquirers = {
        module for module in (paths.ROOT / "pipeline/acquire").glob("*.py")
        if "__pycache__" not in module.parts
    }
    assert acquirers, "pipeline/acquire has no modules — the path must have moved"
    assert acquirers <= set(sources), (
        f"the scan does not cover {sorted(str(m.name) for m in acquirers - set(sources))} — "
        f"every module that talks to a server must be in scope"
    )


def test_no_pipeline_module_reaches_urllib_request_directly():
    """Every outbound request goes through `fetch`, so every request carries an identity.

    The consequence of a module opting out is not a lint complaint: it is an acquisition that works
    on every host without bot protection and fails totally on the first one that has it, discovered
    at the moment someone tries to build a body.
    """
    offenders = [
        str(source.relative_to(paths.ROOT))
        for source in pipeline_sources() if imports_urllib_request(source)
    ]
    assert offenders == [], (
        f"{len(offenders)} module(s) import urllib.request directly: {offenders}. "
        f"Use pipeline.fetch.open_url — a direct request sends the default Python agent, "
        f"which bot-protection edges refuse."
    )


def test_the_scan_would_catch_a_module_that_went_around_fetch(tmp_path: Path):
    """The guard proven against a positive, since a scan that can only say 'clean' says nothing.

    Both spellings, because the two AST node types are separate branches and a test exercising one
    leaves the other free to rot.
    """
    plain = tmp_path / "plain.py"
    plain.write_text("import urllib.request\n\nurllib.request.urlopen('http://example.invalid')\n")
    assert imports_urllib_request(plain)

    from_form = tmp_path / "from_form.py"
    from_form.write_text("from urllib.request import urlretrieve\n")
    assert imports_urllib_request(from_form)

    innocent = tmp_path / "innocent.py"
    innocent.write_text('"""Prose naming urllib.request is not an import."""\nimport json\n')
    assert not imports_urllib_request(innocent)


def test_build_request_carries_the_pipeline_user_agent():
    """The header itself, since the scan can only prove the funnel — never what comes out of it."""
    request = fetch.build_request("https://example.invalid/thing")
    # `.capitalize()` is what urllib does to header names internally, so this is the stored spelling.
    assert request.get_header("User-agent") == fetch.USER_AGENT
    assert "Python-urllib" not in fetch.USER_AGENT, (
        "the agent must not contain the default token the block lists match on"
    )


def test_build_request_passes_the_method_through():
    """A HEAD that silently became a GET would download the body it exists to avoid."""
    assert fetch.build_request("https://example.invalid/x", method="HEAD").get_method() == "HEAD"
    assert fetch.build_request("https://example.invalid/x").get_method() == "GET"


def test_open_url_requires_a_timeout_and_will_not_take_it_positionally():
    """No default, so the next call site cannot quietly omit it.

    An unadorned `urlopen` has no timeout at all, and a stalled host then hangs a pipeline stage
    forever instead of failing it — indistinguishable, from the outside, from a slow download.
    """
    signature = inspect.signature(fetch.open_url)
    timeout = signature.parameters["timeout"]
    assert timeout.default is inspect.Parameter.empty
    assert timeout.kind is inspect.Parameter.KEYWORD_ONLY
    with pytest.raises(TypeError):
        fetch.open_url("https://example.invalid/x")  # pyright: ignore[reportCallIssue]


def test_open_url_hands_urlopen_the_identified_request(monkeypatch: pytest.MonkeyPatch):
    """End to end through the real function, so the wiring is checked and not just the builder."""
    seen: dict[str, object] = {}

    def capture(request, timeout=None):
        seen["agent"] = request.get_header("User-agent")
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        return "response"

    monkeypatch.setattr(urllib.request, "urlopen", capture)
    assert fetch.open_url("https://example.invalid/thing", timeout=7) == "response"
    assert seen == {
        "agent": fetch.USER_AGENT,
        "url": "https://example.invalid/thing",
        "timeout": 7,
    }
