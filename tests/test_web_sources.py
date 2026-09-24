"""The crawl of the files a ZTE router serves to its own web interface.

Moved here with `web_sources.py` in v3.3.25-dev8, from the SMS delete probe
that used to carry both. The assertions are the ones written against the probe:
the subject moved module, and a test rewritten while its subject moves proves
nothing about either.
"""

from typing import Self
from unittest.mock import MagicMock, patch

from custom_components.zte_router_5g import web_sources
from custom_components.zte_router_5g.web_sources import (
    _resolve,
    crawl,
    result_vocabulary,
)

_FAKE_INDEX = (
    "<html><head>"
    '<script src="js/lib/require/require-jquery.js?v=1" data-main="js/main">'
    "</script></head><body></body></html>"
)


_FAKE_MAIN = (
    'require.config({paths:{service:"service",home:"home",md5:"lib/md5"}});'
    # A shim list, which is how the reference device reaches bootstrap.
    'require.config({shim:{md5:["app"]}});'
    # Named in a dependency array and nowhere else, which is how the reference
    # MC7010 reaches nine of the thirty-one files it loads.
    'define(["app"],function(){});'
)
# `service` again, so a name already queued is not fetched twice.
# `md5` is an alias, not a path: resolving it literally invents js/md5.js.


_FAKE_SERVICE = (
    'function zteDelete(){function e(e,t){var n=e.ids.join(";")+";";'
    'return{isTest:Dn,goformId:"DELETE_SMS",msg_id:n,notCallback:!0}}}'
    'function zteDeleteAll(){return{isTest:Dn,goformId:"ALL_DELETE_SMS",notCallback:!0,'
    "which_cgi:e.location}}"
    'var loc={all:"2",device:"1"};which_cgi="2";'
    'function zteDataLimit(){var _={isTest:Dn,goformId:"DATA_LIMIT_SETTING"};'
    "_.data_volume_limit_size=e.limitDataMonth;"
    "_.traffic_clear_date=e.traffic_clear_date;"
    "_.data_volume_limit_switch=e.x;return _}"
    'if(n.ACCESSIBLE_ID_SUPPORT&&"LOGIN"!=e.goformId){'
    'var o=hex_md5(rd0+rd1),u=Bt({nv:"RD"}).RD,c=hex_md5(o+u);e.AD=c}'
    't.ajax({url:"/goform/goform_set_cmd_process"});'
)


def _api(files: dict[str, str] | None = None) -> MagicMock:
    """A router serving a miniature of a ZTE web interface.

    The same shape the reference MC7010 answers with: an index naming its
    scripts through a module loader, a loader config carrying the `paths` map
    and a dependency array, and a bundle holding the payload builders. Anything
    not listed answers 404, which is what a real device does for a name the
    crawl resolved wrongly.
    """
    served = (
        files
        if files is not None
        else {
            "index.html": _FAKE_INDEX,
            "js/main.js": _FAKE_MAIN,
            "js/service.js": _FAKE_SERVICE,
            "js/app.js": "var app=1;",
            "js/language.js": "var lang=1;",
        }
    )

    class _Response:
        def __init__(self, path: str) -> None:
            self._body = served.get(path)
            self.status = 200 if self._body is not None else 404
            self.headers = {"Content-Type": "application/javascript"}

        async def text(self, **_kwargs: object) -> str:
            return self._body or ""

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

    api = MagicMock()
    api.referer = "http://192.168.0.1/"
    api.session.get = MagicMock(
        side_effect=lambda url, **_kw: _Response(url.split("192.168.0.1/", 1)[-1])
    )
    return api


async def test_the_crawl_reaches_a_file_only_a_dependency_array_names() -> None:
    """The module map is not the loader's whole answer.

    On the reference MC7010 the index names three scripts and the `paths` map a
    dozen more, while the browser loads thirty-one. The assignment that
    resolves the write token was in one of the files that difference accounts
    for, and six probe runs never fetched it because the probe read only what
    was declared.
    """
    report = await crawl(_api())

    sources = report["sources"]
    assert "js/app.js" in sources
    assert "js/language.js" in sources


async def test_a_module_reference_resolves_the_way_the_loader_resolves_it() -> None:
    """Extensionless, relative, and text-plugin names all name a real path."""
    assert _resolve("service") == "js/service.js"
    assert _resolve("./home") == "js/home.js"
    assert _resolve("text!tmpl/login.html") == "tmpl/login.html"
    assert _resolve("js/config/config.js") == "js/config/config.js"
    assert _resolve("/js/util.js") == "js/util.js"
    assert _resolve("http://example.invalid/x.js") is None
    assert _resolve("") is None


def test_a_reference_that_names_nothing_fetchable_is_dropped() -> None:
    """A plugin prefix with no resource, and a path that escapes the root."""
    assert _resolve("text!") is None
    assert _resolve("js/../../etc/passwd") is None
    assert _resolve("js/a/../b") == "js/b.js"


async def test_an_alias_is_resolved_through_the_loaders_path_map() -> None:
    """A dependency array asks for `md5`; only the `paths` map says where it is.

    Resolving the alias literally invents `js/md5.js`, which the router does
    not serve. The first rehearsal fabricated eighteen names that way and
    reported every one as a file the device had failed to serve.
    """
    report = await crawl(_api())

    files = report["files"]
    assert "js/lib/md5.js" in files
    assert "js/md5.js" not in files


def test_a_reference_with_no_name_left_is_dropped() -> None:
    """`js/config/` names a directory, and `.js` is not a file."""
    assert _resolve("js/config/") is None


async def test_the_crawl_is_seeded_from_the_static_list_too() -> None:
    """An index that names no scripts is the fault this probe exists for.

    Four downloads from the device of issue #56 reported exactly that, so a
    crawl starting only from what the index declares starts there from nothing.
    """
    # An index that names nothing, which is what four downloads from the
    # device of issue #56 reported.
    report = await crawl(
        _api({"index.html": "<html></html>", "js/service.js": _FAKE_SERVICE})
    )

    assert "js/service.js" in report["sources"]


def test_the_result_vocabulary_separates_equality_from_inequality() -> None:
    """What the firmware compares a write's `result` against, by operator.

    Reported and never acted on, which is the whole point of the split: on the
    reference MC7010 the literals include `fail` and `manual_fail` alongside
    `success`, so a rule that accepted every literal a device compares against
    `result` would report a refused write as carried out. The vocabulary is
    evidence about a device, not a licence to widen the accept set.
    """
    vocabulary = result_vocabulary(
        {
            "js/service.js": (
                'if(e.result=="success"){ok()}'
                'else if("manual_fail"===e.result){no()}'
                'else if(e.result!="0"){other()}'
            ),
            "js/lib/thing.js": 42,
        }
    )

    assert vocabulary["compared_equal"] == ["manual_fail", "success"]
    assert vocabulary["compared_unequal"] == ["0"]


def test_a_source_that_is_not_text_is_skipped_rather_than_failing() -> None:
    """A capture can hold a value that is not a string, and must not raise."""
    assert result_vocabulary({"js/x.js": None}) == {
        "compared_equal": [],
        "compared_unequal": [],
    }


async def test_a_body_cut_to_the_cap_is_reported_as_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file cut to the cap must not read as the whole file.

    The digest is of what the router sent; `returned_bytes` says how much of it
    is here. Without that, a comparison between two devices' downloads reads a
    truncation as a difference in the firmware.
    """
    monkeypatch.setattr(web_sources, "_MAX_RETURN_BYTES", 12)

    report = await crawl(_api({"index.html": _FAKE_INDEX, "js/main.js": _FAKE_MAIN}))

    assert "js/main.js" in report["truncated"]
    assert report["files"]["js/main.js"]["returned_bytes"] == 12
    assert report["files"]["js/main.js"]["bytes"] > 12


async def test_a_third_party_library_is_recorded_but_not_returned() -> None:
    """Its digest identifies it; its source is not what anyone is reading.

    The crawl exists to show what this firmware does, and a bundled copy of
    jQuery is neither specific to the device nor small.
    """
    report = await crawl(
        _api(
            {
                "index.html": _FAKE_INDEX,
                "js/lib/require/require-jquery.js": "var jquery=1;",
            }
        )
    )

    assert "js/lib/require/require-jquery.js" in report["files"]
    assert "js/lib/require/require-jquery.js" not in report["sources"]


async def test_the_model_directory_is_composed_rather_than_referenced() -> None:
    """Nothing names it, so nothing can follow a reference to it.

    On the reference device the model's own directory holds the config that
    overrides the general one, so a build whose write path differs could differ
    there and nowhere else.
    """
    report = await crawl(
        _api(
            {
                "index.html": _FAKE_INDEX,
                "js/main.js": 'var DEVICE:"cpe/MF253V";',
                "js/config/cpe/MF253V/config.js": "var cfg=1;",
            }
        )
    )

    assert "js/config/cpe/MF253V/config.js" in report["files"]


async def test_a_file_the_router_refuses_is_a_finding_not_a_failure() -> None:
    """Forty of forty-five files is the evidence; the five are named."""
    report = await crawl(_api({"index.html": _FAKE_INDEX}))

    assert "js/main.js" in report["missing"]
    assert report["files"]["js/main.js"]["status"] == 404
    assert "js/main.js" not in report["sources"]


async def test_a_file_that_drew_no_answer_is_fetched_once_more() -> None:
    """One dropped request removed every name mined from that file.

    Measured on the MC7010 on 2026-09-24: a diagnostics check failed because
    one pass's crawl lost a single file to a request the router never answered.
    """
    api = _api()
    real_get = api.session.get.side_effect
    dropped: set[str] = set()

    def get(url: str, **kwargs: object):
        path = url.split("192.168.0.1/", 1)[-1]
        if path == "js/service.js" and path not in dropped:
            dropped.add(path)
            raise TimeoutError
        return real_get(url, **kwargs)

    api.session.get = MagicMock(side_effect=get)
    with patch("custom_components.zte_router_5g.web_sources._REFETCH_DELAY_SECONDS", 0):
        report = await crawl(api)

    assert "js/service.js" not in report["missing"]
    assert report["files"]["js/service.js"]["status"] == 200


async def test_a_file_that_never_answers_is_recorded_missing() -> None:
    """The re-fetch is one attempt; a file that fails twice stays a finding."""
    api = _api()
    real_get = api.session.get.side_effect

    def get(url: str, **kwargs: object):
        if url.endswith("js/service.js"):
            raise TimeoutError
        return real_get(url, **kwargs)

    api.session.get = MagicMock(side_effect=get)
    with patch("custom_components.zte_router_5g.web_sources._REFETCH_DELAY_SECONDS", 0):
        report = await crawl(api)

    assert "js/service.js" in report["missing"]
    assert report["files"]["js/service.js"]["status"] is None
    calls = [
        c for c in api.session.get.call_args_list if c.args[0].endswith("js/service.js")
    ]
    assert len(calls) == 2
