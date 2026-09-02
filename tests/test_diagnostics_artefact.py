"""Assertions on the file the user receives, not on what the API returned.

Every test written for the discovery pass so far has asserted against
`run_discovery`'s return value. That is the wrong side of a seam: the result
is copied into the download by `_sanitize_discovery` through an allow-list,
and a field missing from that list is dropped in silence. Branch coverage
cannot see the omission because the list is data, and the loop over it runs
either way.

That is not hypothetical. `canary` was added to `run_discovery` in
v3.3.9-dev5, asserted by five unit tests, and absent from every download the
release produced — the field that records whether the pass could detect its
own degradation. Three downloads taken from the reference MC7010 on
2026-09-02 carry `session`, `session_alive_after` and the full mining trace,
and no `canary` at all.

These tests exist so that the next such field fails the suite rather than the
user.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.zte_router_5g.api import _CORE_PARAMS, ZTERouterAPI
from custom_components.zte_router_5g.diagnostics import (
    DISCOVERY_METADATA_GATED,
    DISCOVERY_METADATA_PUBLISHED,
    _sanitize_discovery,
    _Tokenizer,
    async_get_config_entry_diagnostics,
)

from .conftest import MockResponse


def _discovery_result() -> dict[str, object]:
    """A discovery result carrying every field `run_discovery` produces."""
    return {
        "notes": ["js/service.js: 642 names"],
        "values": {"lte_rsrp": "-97"},
        "session": "fresh login",
        "canary": "network_type",
        "mined_count": 642,
        "mined_names_probed": 501,
        "mined_names_answered": 90,
        "probed_no_answer": ["absent_key"],
        "mined_names": ["lte_rsrp", "absent_key"],
        "write_commands": ["SET_APN"],
        "session_alive_after": True,
    }


@pytest.fixture
def diagnostics_entry(mock_config_entry):
    """A config entry whose coordinator answers a discovery pass."""
    coordinator = MagicMock()
    coordinator.data = None
    coordinator.consecutive_failures = 0
    coordinator.last_update_success = True
    coordinator.last_update_success_time = None
    coordinator.update_interval = None
    coordinator.health_snapshot = {"problem": False, "issues": [], "severity": "ok"}
    coordinator.endpoint_failures = {}
    coordinator.api.last_rejection = None
    coordinator.api.login_metadata = {}
    coordinator.async_run_discovery = AsyncMock(return_value=_discovery_result())
    mock_config_entry.runtime_data = coordinator
    object.__setattr__(mock_config_entry, "data", {"model": "MC7010"})
    object.__setattr__(
        mock_config_entry, "options", {"host": "192.168.0.1", "password": "hunter2"}
    )
    return mock_config_entry


# ---------------------------------------------------------------------------
# The seam itself
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_discovery_field_is_classified(mock_aiohttp_client):
    """A new field must be published or excluded deliberately, never dropped.

    This runs the real pass and compares the keys it produces against the two
    sets in `diagnostics`. Adding a field to `run_discovery` without deciding
    what the download does with it fails here, which is the check that was
    missing when `canary` shipped unpublished.
    """
    api = ZTERouterAPI(mock_aiohttp_client, "192.168.0.1", "admin", "password")
    api.cookies = {"stok": "live"}
    api.session_active = True
    mock_aiohttp_client.get_response = MockResponse(
        json_data={_CORE_PARAMS[0]: "value", "wan_connect_status": "connected"}
    )

    with (
        patch.object(api, "logout", AsyncMock()),
        patch.object(api, "login", AsyncMock()),
    ):
        result = await api.run_discovery()

    classified = DISCOVERY_METADATA_PUBLISHED | DISCOVERY_METADATA_GATED
    assert set(result) == classified, (
        f"unclassified: {sorted(set(result) - classified)}, "
        f"classified but not produced: {sorted(classified - set(result))} — "
        "every discovery field belongs in DISCOVERY_METADATA_PUBLISHED or "
        "DISCOVERY_METADATA_GATED"
    )


def test_the_two_field_sets_do_not_overlap() -> None:
    """A field handled specially must not also be copied verbatim."""
    assert not (DISCOVERY_METADATA_PUBLISHED & DISCOVERY_METADATA_GATED)


def test_every_published_field_survives_sanitization() -> None:
    """The allow-list is the contract; assert it is honoured, not just held."""
    out = _sanitize_discovery(_discovery_result(), _Tokenizer())

    for field in DISCOVERY_METADATA_PUBLISHED:
        assert field in out, f"{field} was dropped by _sanitize_discovery"


def test_a_field_absent_from_the_result_is_not_invented() -> None:
    """An older or aborted result publishes what it has and nothing more."""
    aborted = {"notes": ["discovery aborted: OSError: gone"], "values": {}}

    out = _sanitize_discovery(aborted, _Tokenizer())

    assert "canary" not in out
    assert out["notes"] == ["discovery aborted: OSError: gone"]


# ---------------------------------------------------------------------------
# The artefact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_download_records_which_key_guarded_the_pass(diagnostics_entry):
    """Without the canary a reader cannot weigh `probed_no_answer` at all.

    "These 444 names do not exist on this firmware" and "we may not have been
    logged in" are different claims, and the canary is what separates them.
    """
    diagnostics_entry.runtime_data.async_run_discovery = AsyncMock(
        return_value=_discovery_result()
    )

    result = await async_get_config_entry_diagnostics(None, diagnostics_entry)

    assert result["discovery"]["canary"] == "network_type"


@pytest.mark.asyncio
async def test_the_download_says_so_when_no_canary_was_available(diagnostics_entry):
    """A pass that cannot detect its own degradation must admit it."""
    unguarded = _discovery_result() | {"canary": "unavailable"}
    diagnostics_entry.runtime_data.async_run_discovery = AsyncMock(
        return_value=unguarded
    )

    result = await async_get_config_entry_diagnostics(None, diagnostics_entry)

    assert result["discovery"]["canary"] == "unavailable"


@pytest.mark.asyncio
async def test_the_download_carries_the_whole_discovery_trace(diagnostics_entry):
    """The counts a reader needs to judge a pass, asserted where they land."""
    diagnostics_entry.runtime_data.async_run_discovery = AsyncMock(
        return_value=_discovery_result()
    )

    result = await async_get_config_entry_diagnostics(None, diagnostics_entry)
    discovery = result["discovery"]

    assert discovery["session"] == "fresh login"
    assert discovery["session_alive_after"] is True
    assert discovery["mined_names_probed"] == 501
    assert discovery["mined_names_answered"] == 90
    assert discovery["probed_no_answer"] == ["absent_key"]
    assert discovery["notes"] == ["js/service.js: 642 names"]


@pytest.mark.asyncio
async def test_the_canary_name_is_not_treated_as_a_discovered_value(
    diagnostics_entry,
):
    """Published as metadata, so it must not also appear as a probed value."""
    diagnostics_entry.runtime_data.async_run_discovery = AsyncMock(
        return_value=_discovery_result()
    )

    result = await async_get_config_entry_diagnostics(None, diagnostics_entry)

    assert "network_type" not in result["discovery"]["values"]
    assert "network_type" not in result["discovery"]["verdicts"]


@pytest.mark.asyncio
async def test_an_aborted_note_does_not_publish_the_router_address(
    diagnostics_entry,
):
    """`discovery aborted: {err}` carries whatever the exception said.

    An aiohttp connection failure names the host and port it could not reach,
    and notes are published verbatim otherwise — so the one field in the
    discovery block holding free text is also the one that can leak the LAN
    address the rest of the file tokenizes.
    """
    leaky = _discovery_result() | {
        "notes": ["discovery aborted: Cannot connect to host 10.11.12.13:80"]
    }
    diagnostics_entry.runtime_data.async_run_discovery = AsyncMock(return_value=leaky)

    result = await async_get_config_entry_diagnostics(None, diagnostics_entry)

    assert "10.11.12.13" not in json.dumps(result)
    # Tokenized, not blanked: the reader still learns a connection failed.
    assert "Cannot connect to host" in result["discovery"]["notes"][0]


def test_an_ordinary_note_is_left_alone() -> None:
    """The sweep must not damage the mining trace, which is the useful part."""
    out = _sanitize_discovery(_discovery_result(), _Tokenizer())

    assert out["notes"] == ["js/service.js: 642 names"]
