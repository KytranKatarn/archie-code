"""The hub plan branch must send the op-array SCHEMA (#6038).

The offline branch has always used `format=OPS_SCHEMA`; the hub branch could not
express a constraint at all until archie-platform #2846 added the passthrough. The
two paths were therefore NOT equivalent, and once a source file was injected into
the prompt (#380 Phase 2b) the unconstrained model returned Python in a fenced code
block instead of the JSON op array (KB #296229).

⚠️ Receiver without sender is not a fix. The endpoint accepting `format` changes
nothing while `dhq_complete` builds no `format` key — these tests pin the SENDER.
"""

from __future__ import annotations

import asyncio

import pytest

from archie_engine.build_loop import OPS_SCHEMA
from archie_engine.hub.connector import HubConnector


class _Auth:
    def get_headers(self):
        return {"Content-Type": "application/json"}


def _connector_capturing(seen):
    hc = HubConnector(hub_url="http://h", auth=_Auth())

    async def fake_post(path, data=None, timeout=None):
        seen["path"] = path
        seen["data"] = data
        return {"response": "[]"}

    hc.post = fake_post
    return hc


class TestSenderPutsFormatOnTheWire:
    def test_schema_is_sent_when_supplied(self):
        seen = {}
        hc = _connector_capturing(seen)
        asyncio.run(hc.dhq_complete("p", format=OPS_SCHEMA))
        assert seen["data"]["format"] == OPS_SCHEMA

    def test_the_schema_is_an_ARRAY_contract(self):
        """Bare format='json' would not pin this — that is the whole point."""
        assert OPS_SCHEMA.get("type") == "array"

    def test_bare_json_string_also_travels(self):
        seen = {}
        hc = _connector_capturing(seen)
        asyncio.run(hc.dhq_complete("p", format="json"))
        assert seen["data"]["format"] == "json"

    def test_it_still_targets_the_dhq_endpoint(self):
        seen = {}
        hc = _connector_capturing(seen)
        asyncio.run(hc.dhq_complete("p", format=OPS_SCHEMA))
        assert seen["path"] == "/api/internal/dhq/chat"


class TestBackwardCompatibility:
    """⚠️ Every other dhq_complete caller omits format and must be unchanged."""

    def test_no_format_means_the_key_is_ABSENT_not_null(self):
        seen = {}
        hc = _connector_capturing(seen)
        asyncio.run(hc.dhq_complete("p"))
        assert "format" not in seen["data"], "a null format would be a 400 platform-side"

    def test_other_optional_params_still_omitted_when_unset(self):
        seen = {}
        hc = _connector_capturing(seen)
        asyncio.run(hc.dhq_complete("p"))
        for k in ("capability", "prefer_agent", "module_id", "model"):
            assert k not in seen["data"]

    def test_the_success_path_still_returns_text(self):
        seen = {}
        hc = _connector_capturing(seen)
        assert asyncio.run(hc.dhq_complete("p", format=OPS_SCHEMA)) == "[]"
