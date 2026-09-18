"""Tests for diagnostics platform."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.zte_router_5g.diagnostics import (
    CARRIER_KEYS,
    CELL_KEYS,
    IP_KEYS,
    TO_REDACT,
    async_get_config_entry_diagnostics,
)


async def test_diagnostics_basic(mock_coordinator, mock_config_entry):
    """Test that diagnostics returns expected structure with data and redaction."""
    mock_coordinator.consecutive_failures = 0
    mock_coordinator.last_update_success = True
    mock_coordinator.last_update_success_time = MagicMock()
    mock_coordinator.last_update_success_time.isoformat.return_value = (
        "2024-01-15T10:30:00"
    )
    mock_coordinator.data = {
        "wan_ipaddr": "1.2.3.4",
        "signal_strength": 75,
        "password": "secret",
    }
    mock_config_entry.runtime_data = mock_coordinator

    result = await async_get_config_entry_diagnostics(None, mock_config_entry)

    # Entry info
    assert result["entry"]["title"] == "My ZTE Router"
    assert result["entry"]["data"]["model"] == "MC7010"
    assert result["entry"]["options"]["password"] == "**REDACTED**"
    assert result["entry"]["options"]["username"] == "**REDACTED**"

    # Coordinator info
    assert result["coordinator"]["consecutive_failures"] == 0
    assert result["coordinator"]["last_update_success"] is True
    assert result["coordinator"]["last_update_success_time"] == "2024-01-15T10:30:00"
    assert result["coordinator"]["data_available"] is True

    # Data sanitization. The IP is pseudonymized rather than blanked so it can
    # still be cross-referenced within the file (dev_standards Section 20);
    # `password` has no referential role and is blanked outright.
    assert result["data"]["signal_strength"] == 75
    assert result["data"]["wan_ipaddr"].startswith("ip-")
    assert "1.2.3.4" not in str(result)
    assert result["data"]["password"] == "**REDACTED**"


async def test_diagnostics_no_data(mock_coordinator, mock_config_entry):
    """Test diagnostics when coordinator.data is None."""
    mock_coordinator.data = None
    mock_coordinator.last_update_success_time = None
    mock_config_entry.runtime_data = mock_coordinator

    result = await async_get_config_entry_diagnostics(None, mock_config_entry)

    assert result["data"] == {}
    assert result["coordinator"]["data_available"] is False
    assert result["coordinator"]["last_update_success_time"] is None


async def test_sensitive_keys_are_categorized():
    """Every sensitive key must be handled, blanked or tokenized.

    Key-name membership is a weak assertion on its own — see
    test_diagnostics_sanitization.py for the properties that actually prove the
    output is safe. This only guards the categorization itself.
    """
    # No referential value — blanked.
    assert "password" in TO_REDACT
    assert "username" in TO_REDACT
    assert "imei" in TO_REDACT

    # Cross-reference value — tokenized, not blanked.
    assert "wan_ipaddr" in IP_KEYS
    assert "lan_ipaddr" in IP_KEYS
    assert "cell_id" in CELL_KEYS

    # Carrier identity locates the subscriber; no diagnostic value.
    assert "network_provider" in CARRIER_KEYS
    assert "mdm_mcc" in CARRIER_KEYS


def test_witness_list_survives_a_collaborator_that_did_not_return_a_list():
    """`session_witnesses` is read through a guard that answers `None` on error.

    The download is serialized only after every section has been built, so a
    value of the wrong type fails the whole file at the last moment and past
    every other check. An unreadable witness list is reported as no witnesses.
    """
    from custom_components.zte_router_5g.diagnostics import _string_list

    assert _string_list(None) == []
    assert _string_list("wan_connect_status") == []
    assert _string_list(["wan_connect_status", 7, None]) == ["wan_connect_status"]


async def test_the_session_flag_state_is_published(mock_coordinator, mock_config_entry):
    """Whether this device implements `loginfo`, and what the check has done.

    The field that settles the one question the reference hardware cannot
    answer. The MC888 Pro has never been observed with a dead session and its
    downloads redact the flag's value by name, so whether it implements the key
    at all is unknown — and that decides whether the pre-write check applies
    there. `supported` answers it from that device's next download, with no
    write and nothing asked of its owner.

    The raw value is deliberately absent: it is denied by name and is not what
    anyone needs.
    """
    mock_coordinator.data = {}
    mock_coordinator.api.session_flag_report = MagicMock(
        return_value={
            "supported": True,
            "confirmed_on_firmware": "IRL_H3G_MC7010DV1.0.0B03",
            "checks": {"checks": 4, "not_confirmed": 1},
        }
    )
    mock_config_entry.runtime_data = mock_coordinator

    result = await async_get_config_entry_diagnostics(None, mock_config_entry)

    assert result["session_flag"]["supported"] is True
    assert result["session_flag"]["confirmed_on_firmware"].startswith("IRL")
    assert result["session_flag"]["checks"]["checks"] == 4
    assert "loginfo" not in str(result["session_flag"])


async def test_a_check_that_did_not_confirm_survives_the_download(
    mock_coordinator, mock_config_entry
):
    """The record of a failure must outlive the reads that produce the file.

    `last_session_check` is replaced by every check, and producing a download
    reads the router. Reading it afterwards therefore describes the collection,
    which on 2026-09-14 produced a wrong conclusion about the fault the file
    had been collected to explain. The companion field is never overwritten by
    a confirmation, and is historical by construction.
    """
    mock_coordinator.data = {}
    mock_coordinator.api.last_session_check = {
        "source": "session_flag",
        "verdict": "confirmed",
    }
    mock_coordinator.api.last_non_confirmed_session_check = {
        "source": "session_flag",
        "verdict": "denied",
        "at": "2026-09-14T12:00:00+00:00",
    }
    mock_config_entry.runtime_data = mock_coordinator

    result = await async_get_config_entry_diagnostics(None, mock_config_entry)

    assert result["last_session_check"]["verdict"] == "confirmed"
    assert result["last_non_confirmed_session_check"]["verdict"] == "denied"
    assert result["last_non_confirmed_session_check"]["at"].startswith("2026-09-14")


async def test_the_sources_publish_only_when_a_write_has_failed(
    mock_coordinator, mock_config_entry
):
    """The manifest always, the sources on cause, and the cause is named.

    Measured on the reference MC7010 on 2026-09-14: the file list costs 5.4 kB
    and the sources 237 kB, against 49 kB for an entire ordinary download.
    Attaching a quarter of a megabyte of firmware JavaScript to every report,
    to answer a question almost nobody has, is how a diagnostics file gets left
    unread.
    """
    mock_coordinator.data = {}
    mock_coordinator.api.write_failures = []
    crawled = {
        "files": {"js/service.js": {"status": 200, "bytes": 4}},
        "sources": {"js/service.js": 'if(e.result=="success"){ok()}'},
        "fetched": 1,
    }
    mock_config_entry.runtime_data = mock_coordinator

    with patch(
        "custom_components.zte_router_5g.web_sources.crawl",
        new=AsyncMock(return_value=dict(crawled)),
    ):
        quiet = await async_get_config_entry_diagnostics(None, mock_config_entry)

    assert quiet["web_sources"]["files"]
    assert quiet["web_sources"]["sources_included"] is False
    assert quiet["web_sources"]["sources_included_because"] is None
    assert "sources" not in quiet["web_sources"]
    # The vocabulary publishes either way: it is a few short literals, and it
    # is what answers whether another device speaks a vocabulary this one does
    # not. See `web_sources.result_vocabulary` for why it is never acted on.
    assert quiet["web_sources"]["result_vocabulary"]["compared_equal"] == ["success"]

    mock_coordinator.api.write_failures = [{"cmd": "DELETE_SMS"}]
    with patch(
        "custom_components.zte_router_5g.web_sources.crawl",
        new=AsyncMock(return_value=dict(crawled)),
    ):
        loud = await async_get_config_entry_diagnostics(None, mock_config_entry)

    assert loud["web_sources"]["sources_included"] is True
    assert "1 write failure" in loud["web_sources"]["sources_included_because"]
    assert loud["web_sources"]["sources"]["js/service.js"]
    assert loud["web_sources"]["sources_are_unswept"] is True


async def test_a_source_carrying_a_known_identifier_is_swept_and_named(
    mock_coordinator, mock_config_entry
):
    """The exemption is checked against this download's own tokenized values.

    Served scripts are firmware and carry nothing belonging to whoever asked
    for the download, on both devices measured — which is two builds. A build
    embedding a subscriber identifier would otherwise reach a file written to
    be attached to a public issue.
    """
    mock_coordinator.data = {"imei": "864155042229309"}
    mock_coordinator.api.write_failures = [{"cmd": "DELETE_SMS"}]
    crawled = {
        "files": {
            "js/service.js": {"status": 200, "bytes": 4},
            "js/leaky.js": {"status": 200, "bytes": 4},
        },
        "sources": {
            "js/service.js": 'if(e.result=="success"){ok()}',
            "js/leaky.js": 'var d="864155042229309";',
        },
        "fetched": 2,
    }
    mock_config_entry.runtime_data = mock_coordinator

    with patch(
        "custom_components.zte_router_5g.web_sources.crawl",
        new=AsyncMock(return_value=dict(crawled)),
    ):
        result = await async_get_config_entry_diagnostics(None, mock_config_entry)

    section = result["web_sources"]
    assert section["sources_swept"] == ["js/leaky.js"]
    assert section["sources_are_unswept"] is False
    assert "864155042229309" not in json.dumps(result, default=str)
    # The clean file is still published exactly as the router served it.
    assert section["sources"]["js/service.js"] == 'if(e.result=="success"){ok()}'


async def test_a_crawl_that_answers_nothing_costs_a_field_not_the_file(
    mock_coordinator, mock_config_entry
):
    """A router that refuses its own scripts must not cost the whole download."""
    mock_coordinator.data = {}
    mock_config_entry.runtime_data = mock_coordinator

    with patch(
        "custom_components.zte_router_5g.web_sources.crawl",
        new=AsyncMock(side_effect=OSError("refused")),
    ):
        result = await async_get_config_entry_diagnostics(None, mock_config_entry)

    assert result["web_sources"] is None
    assert result["data"] is not None
