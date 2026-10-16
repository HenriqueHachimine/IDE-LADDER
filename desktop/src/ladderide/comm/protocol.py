"""Constantes do protocolo LDP, carregadas de shared/specifications/protocol.json."""
from __future__ import annotations

import json
from enum import IntEnum

from ..core.isa import ISA_PATH

PROTOCOL_PATH = ISA_PATH.with_name("protocol.json")
with open(PROTOCOL_PATH, encoding="utf-8") as _f:
    SPEC = json.load(_f)

VERSION: int = SPEC["version"]
SOF = bytes(SPEC["sof"])
MAX_PAYLOAD: int = SPEC["max_payload"]
MAX_CHUNK: int = SPEC["max_chunk"]
FRAME_TIMEOUT_MS: int = SPEC["frame_timeout_ms"]
RESPONSE_FLAG: int = SPEC["response_flag"]
ERROR_FLAG: int = SPEC["error_flag"]

Cmd = IntEnum("Cmd", {c["name"]: c["code"] for c in SPEC["commands"]})
ProtoError = IntEnum("ProtoError", {e["name"]: e["code"] for e in SPEC["errors"]})
DevState = IntEnum("DevState", {s["name"]: s["code"] for s in SPEC["states"]})
Fault = IntEnum("Fault", {f["name"]: f["code"] for f in SPEC["faults"]})
ERROR_TEXT = {e["code"]: e["description"] for e in SPEC["errors"]}
FAULT_TEXT = {f["code"]: f["description"] for f in SPEC["faults"]}
