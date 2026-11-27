import json

import pytest

from cogs.Modules.embeds import IsV2, ParseJSON, V2Components

V2 = {"flags": 32768, "components": [{"type": 17, "components": [{"type": 10, "content": "## Hola"}]}]}
CLASSIC = {"content": "hola", "embeds": [{"title": "Normas", "description": "..."}]}


def test_detects_v2_in_every_shape():
    assert IsV2(V2)
    assert IsV2(V2["components"])  # just the list
    assert IsV2({"components": V2["components"]})  # without flags
    assert IsV2({"messages": [{"data": V2}]})  # discohook backup
    assert not IsV2(CLASSIC)
    assert not IsV2({"content": "x", "components": [{"type": 1, "components": [{"type": 2, "style": 5, "url": "https://a"}]}]})


def test_classic_json_still_goes_to_the_embed_editor():
    assert V2Components(json.dumps(CLASSIC)) is None
    assert ParseJSON(json.dumps(CLASSIC))["embeds"][0]["title"] == "Normas"
    assert V2Components("{not json") is None  # the classic parser reports it


def test_v2_json_is_checked():
    assert V2Components(json.dumps(V2))[0]["type"] == 17
    assert V2Components(json.dumps({"messages": [{"data": V2}]}))[0]["type"] == 17
    with pytest.raises(ValueError, match="enlace"):
        V2Components(json.dumps({"flags": 32768, "components": [{"type": 1, "components": [{"type": 2, "style": 1, "custom_id": "x"}]}]}))
    with pytest.raises(ValueError, match="content"):
        V2Components(json.dumps({"flags": 32768, "content": "hola", "components": V2["components"]}))
