import pytest

from core.mcp.protocol import ProtocolError, decode, encode


def test_roundtrip_preserves_turkish_text():
    msg = {"jsonrpc": "2.0", "id": 1, "result": {"text": "ısınma turları"}}
    assert decode(encode(msg)) == msg


def test_encode_emits_single_newline_terminated_line():
    assert encode({"id": 1}).endswith(b"\n") and encode({"id": 1}).count(b"\n") == 1


def test_decode_invalid_json_raises_protocol_error():
    with pytest.raises(ProtocolError):
        decode(b"{oops\n")


def test_decode_non_object_raises_protocol_error():
    with pytest.raises(ProtocolError):
        decode(b"[1, 2]\n")
