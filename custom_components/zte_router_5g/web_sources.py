"""Read the files the router serves to its own web interface.

The crawl follows the device's own references — the index's script tags, the
loader's `paths` map, dependency arrays and module literals — and returns one
record per file with the source of everything that is not a third-party
library.

**It lived in the SMS delete probe until v3.3.25-dev8.** That was a service a
person had to run, which deleted real messages and was visible to anyone who
scrolled far enough in Developer Tools. The crawl itself writes nothing and
deletes nothing, and it answers questions no other instrument can — which
command spellings a firmware uses, where it assigns `RD`, which digest it
implements — so it moved into the diagnostics download, where no action is run
and none can misfire, and the probe was removed around it.

Nothing here is specific to one model: every path is either seeded from the
shared bundle list or discovered from the device's own files.
"""

import hashlib
import re
from typing import Any

import aiohttp

from .const import JS_BUNDLES

_SCRIPT_SRC = re.compile(r"""<script[^>]+src\s*=\s*["']([^"']+)["']""")

_DATA_MAIN = re.compile(r"""data-main\s*=\s*["']([^"']+)["']""")
# `require.config({paths:{name:"path", ...}})`, which is where a module loader
# keeps the list an index page does not carry.

_REQUIRE_PATHS = re.compile(r"""paths\s*:\s*\{([^}]*)\}""")

_PATH_PAIR = re.compile(r"""["']?([\w$-]+)["']?\s*:\s*["']([^"']+)["']""")

# What a bundle is searched for, and what each occurrence is worth capturing.

_DEP_ARRAY = re.compile(r"""(?:define|require)\s*\(\s*\[([^\]]{0,4000})\]""")
# `shim:{jq_simplemodal:["lib/bootstrap"]}`. The loader follows these; the
# first rehearsal did not, and missed `js/lib/bootstrap.js`.
#
# Scoped to the shim block rather than to any bracketed list of strings: the
# looser form matched a table of country codes and filled the crawl's budget
# with two hundred names the router has never served.

_SHIM_BLOCK = re.compile(r"""shim\s*:\s*\{([^}]{0,4000})\}""")
# `DEVICE:"cpe/MF253V"`, which names a directory of model-specific modules the
# loader composes at runtime. Nothing refers to those files by name, so no
# amount of reference-following reaches them.

_DEP_ITEM = re.compile(r"""["']([^"']{1,120})["']""")
# A string that could be a module path: no spaces, no scheme, not a sentence.

_DEVICE = re.compile(r"""\bDEVICE\s*:\s*["']([\w./-]{1,60})["']""")

_MODULE_LITERAL = re.compile(r"""["']((?:\.{0,2}/)?[\w][\w./-]{1,80})["']""")

# Names a loader can reach without ever naming them in a file we parse. Swept
# once at the end so a crawl that stalls still returns the modules that carry
# the write path.

_KNOWN_MODULES: tuple[str, ...] = (
    "js/main.js",
    "js/app.js",
    "js/service.js",
    "js/util.js",
    "js/router.js",
    "js/home.js",
    "js/login.js",
    "js/logout.js",
    "js/language.js",
    "js/tooltip.js",
    "js/status/statusBar.js",
    "js/config/config.js",
    "js/config/menu.js",
    "js/lib/md5.js",
    "js/lib/base64.js",
    "tmpl/login.html",
)

# Given `DEVICE:"cpe/MF253V"`, the files that directory is known to hold.

_DEVICE_MODULES: tuple[str, ...] = ("config.js", "menu_bridge.js")

# A library is followed, because it names modules, but not returned: jQuery and
# Knockout are a megabyte that tells us nothing about this firmware.

_LIB_PREFIX = "js/lib/"

# The crawl, capped. A loader can name a great many files and a slow router
# turns that into a timeout.
# Ninety rather than sixty: the reference MC7010 used 43, and the MC888 Pro's
# web UI is a later and larger one that has never been measured. A crawl capped
# part-way through returns a partial answer to a question that costs a round
# trip with the reporter to ask again.

_MAX_RETURN_BYTES = 400_000

_MAX_CRAWL_FILES = 90

_MAX_CRAWL_BYTES = 3_000_000


async def _fetch_text(api: Any, path: str) -> tuple[int | None, list[str], str]:
    """Fetch one page or script, returning status, header names and body."""
    url = f"{api.referer}{path.lstrip('/')}"
    try:
        async with api.session.get(
            url,
            headers={"Referer": f"{api.referer}index.html"},
            timeout=aiohttp.ClientTimeout(total=15),
            ssl=False,
        ) as response:
            body = await response.text(errors="replace")
            return response.status, sorted(response.headers), body
    except Exception as err:  # noqa: BLE001 - a miss is a finding, not a failure
        return None, [], f"{type(err).__name__}: {err}"


def _resolve(
    name: str,
    base: str = "js/",
    aliases: dict[str, str] | None = None,
) -> str | None:
    """A module reference as a path this probe can fetch, or None.

    RequireJS names are extensionless and may be relative. `text!tmpl/x.html`
    names a template through the text plugin. Most of them are aliases rather
    than paths: a dependency array asks for `jquery`, and the `paths` map says
    where `jquery` lives. Resolving without that map invents `js/jquery.js`,
    which does not exist — eighteen of the fifty-one names the first rehearsal
    fetched were fabricated that way, and each one was reported as a file the
    router failed to serve.
    """
    name = name.strip()
    if not name or "://" in name or name.startswith(("//", "#")):
        return None
    if "!" in name:
        name = name.split("!", 1)[1]
        if not name:
            return None
    name = name.split("?", 1)[0]
    if aliases:
        head, _sep, rest = name.partition("/")
        if head in aliases:
            name = aliases[head] + ("/" + rest if rest else "")
    if name.startswith("/"):
        name = name[1:]
    elif not name.startswith(("js/", "tmpl/", "css/", "img/")):
        name = base + name
    while "/./" in name:
        name = name.replace("/./", "/")
    while "/../" in name:
        head, _sep, rest = name.partition("/../")
        name = head.rsplit("/", 1)[0] + "/" + rest if "/" in head else rest
    if not name.endswith((".js", ".html")):
        name += ".js"
    if any(part in {"", ".", ".."} for part in name.split("/")):
        return None
    if name.rsplit("/", 1)[-1] in {".js", ".html"}:
        return None
    return name


def _aliases(text: str) -> dict[str, str]:
    """The loader's `paths` map: the alias a dependency array asks for."""
    return {
        pair.group(1): pair.group(2)
        for block in _REQUIRE_PATHS.finditer(text)
        for pair in _PATH_PAIR.finditer(block.group(1))
    }


def _referenced(
    text: str,
    aliases: dict[str, str] | None = None,
    literals: bool = True,
) -> set[str]:
    """Every module path one file refers to, by any of the three routes.

    `literals` is the loosest of the three and is turned off for third-party
    libraries, whose documentation comments carry example paths — the first
    rehearsal followed `js/one/two/three.js` out of the RequireJS banner and
    reported it as a file the router failed to serve.
    """
    names: set[str] = set()
    for block in _REQUIRE_PATHS.finditer(text):
        for pair in _PATH_PAIR.finditer(block.group(1)):
            names.add(pair.group(2))
    for pattern in (_DEP_ARRAY, _SHIM_BLOCK):
        for block in pattern.finditer(text):
            names.update(item.group(1) for item in _DEP_ITEM.finditer(block.group(1)))
    if literals:
        names.update(
            match.group(1)
            for match in _MODULE_LITERAL.finditer(text)
            if match.group(1).endswith((".js", ".html"))
        )
    resolved = {_resolve(name, aliases=aliases) for name in names}
    return {name for name in resolved if name}


async def crawl(api: Any) -> dict[str, Any]:
    """Follow the router's own references until no new file appears.

    Returns one record per file — status, byte count and digest — and the
    source of every file that is not a third-party library. The digest is
    there so two devices' downloads can be compared without diffing a
    megabyte, and so a truncated body is visible as such.
    """
    # Seeded from the static list as well as the index. Four downloads from
    # the MC888 Pro of issue #56 reported "index: no scripts named", so a crawl
    # that starts only from what the index declares starts, on that device,
    # from nothing.
    queue: list[str] = ["index.html", "js/main.js", *JS_BUNDLES]
    seen: set[str] = set()
    files: dict[str, Any] = {}
    sources: dict[str, str] = {}
    total = 0
    truncated: list[str] = []
    missing: list[str] = []
    aliases: dict[str, str] = {}

    async def take(path: str) -> str:
        nonlocal total
        status, _headers, body = await _fetch_text(api, path)
        size = len(body)
        record: dict[str, Any] = {"status": status, "bytes": size}
        if status == 200:
            record["sha256"] = hashlib.sha256(body.encode(errors="replace")).hexdigest()
            if not path.startswith(_LIB_PREFIX):
                kept = body[:_MAX_RETURN_BYTES]
                if len(kept) < size:
                    truncated.append(path)
                    record["returned_bytes"] = len(kept)
                sources[path] = kept
                total += len(kept)
        else:
            missing.append(path)
        files[path] = record
        return body if status == 200 else ""

    while queue and len(seen) < _MAX_CRAWL_FILES and total < _MAX_CRAWL_BYTES:
        # Nothing reaches the queue twice: every producer below checks both
        # `seen` and `queue` before appending.
        path = queue.pop(0)
        seen.add(path)
        body = await take(path)
        if not body or path.endswith(".html"):
            # A template refers to nothing this crawl can follow, and an index
            # is seeded separately below.
            if path == "index.html":
                for src in _SCRIPT_SRC.findall(body) + _DATA_MAIN.findall(body):
                    resolved = _resolve(src, aliases=aliases)
                    if resolved and resolved not in seen and resolved not in queue:
                        queue.append(resolved)
            continue
        aliases.update(_aliases(body))
        for name in sorted(
            _referenced(body, aliases, not path.startswith(_LIB_PREFIX))
        ):
            if name not in seen and name not in queue:
                queue.append(name)

    # The model-specific directory, composed rather than referenced. On the
    # reference device it holds the config that overrides the general one, so a
    # build whose write path differs could differ here and nowhere else.
    device_modules: list[str] = []
    for text in sources.values():
        for match in _DEVICE.finditer(text):
            device_modules += [
                f"js/config/{match.group(1)}/{name}" for name in _DEVICE_MODULES
            ]

    for known in (*_KNOWN_MODULES, *dict.fromkeys(device_modules)):
        if known not in seen and len(seen) < _MAX_CRAWL_FILES:
            seen.add(known)
            await take(known)

    return {
        "files": files,
        "sources": sources,
        "fetched": len(files),
        "returned": len(sources),
        "returned_bytes": total,
        "missing": missing,
        "truncated": truncated,
        "unvisited_queue": queue[:20],
        "capped": len(seen) >= _MAX_CRAWL_FILES or total >= _MAX_CRAWL_BYTES,
    }


# Every literal the device's own scripts compare a `result` against, with the
# operator used. Both orders, because minified code writes each of them.
_RESULT_TEST = re.compile(
    r"""result\s*(===?|!==?)\s*["']([^"']{1,24})["']"""
    r"""|["']([^"']{1,24})["']\s*(===?|!==?)\s*[\w.]*\bresult\b"""
)


def result_vocabulary(sources: dict[str, Any]) -> dict[str, list[str]]:
    """What this firmware compares a write's `result` against, by operator.

    **Reported, never acted on, and the measurement says why.** On the
    reference MC7010 the literals tested against `result` are `success` (54
    across both equality forms), `manual_success`, `manual_fail`, `fail` and
    the digits `0`, `1`, `3`, `4` and `5`. A rule that accepted every literal a
    device compares against `result` would accept `fail` — a refused write
    reported to the user as carried out, which is the fault this project
    exists to remove, installed deliberately.

    Minified script gives no dependable way to tell which branch a literal
    belongs to: the comparison is there, the consequence is a jump. So the
    vocabulary is published as evidence and the accept set stays fail-closed —
    a `result` the integration does not recognise remains a refusal.

    What this answers is the question the reference hardware cannot: whether
    another device's firmware speaks a vocabulary this one does not. That
    arrives with the next download from such a device, and a widening can then
    be argued from its scripts rather than from ours.
    """
    equality: set[str] = set()
    inequality: set[str] = set()
    for text in sources.values():
        if not isinstance(text, str):
            continue
        for match in _RESULT_TEST.finditer(text):
            operator = match.group(1) or match.group(4)
            literal = match.group(2) if match.group(2) is not None else match.group(3)
            target = equality if operator.startswith("=") else inequality
            target.add(literal)
    return {
        "compared_equal": sorted(equality),
        "compared_unequal": sorted(inequality),
    }
