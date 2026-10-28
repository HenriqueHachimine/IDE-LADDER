"""Executa os vetores compartilhados na VM Python e compara com a VM C."""
from __future__ import annotations

import struct

import pytest

from conftest import VECTORS, load_json
from ladderide.core import ImageValidationError, LadderVM, assemble, build_image, decode, encode
from ladderide.core.asm import parse_operand
from ladderide.core.crc import crc32
from ladderide.core.isa import WORD_READ_AREAS, ImageError

SCAN_CASES = [case for f in sorted((VECTORS / "scan").glob("*.json"))
              for case in load_json(f"scan/{f.name}")]
ERROR_DOC = load_json("image-errors.json")


def expand_steps(steps: list[dict]) -> list[tuple[int, int, dict | None]]:
    """Converte passos em varreduras (dt, mascara_de_entradas, expect_ou_None)."""
    inputs = 0
    scans = []
    for step in steps:
        for name, value in step.get("inputs", {}).items():
            _, index = parse_operand(name)
            inputs = inputs | (1 << index) if value else inputs & ~(1 << index)
        repeat = step.get("repeat", 1)
        for k in range(repeat):
            scans.append((step.get("dt", 10), inputs, step.get("expect") if k == repeat - 1 else None))
    return scans


def read_value(vm: LadderVM, key: str) -> int:
    if key == "SCAN":
        return vm.scan_count
    area, index = parse_operand(key)
    if area in WORD_READ_AREAS:                  # Nk, Tn.ACC, Cn.PRE, IW0...
        return vm.read_word(area, index)
    return int(vm.read_bit(area, index))


def run_python(case: dict) -> tuple[bytes, list[tuple[int, int]], list[str]]:
    image = build_image(assemble("\n".join(case["program"])))
    vm = LadderVM(decode(image))
    scans = expand_steps(case["steps"])
    lines = []
    for n, (dt, inputs, expect) in enumerate(scans, start=1):
        vm.scan(inputs, dt)
        lines.append(vm.dump_line())
        for key, want in (expect or {}).items():
            got = read_value(vm, key)
            assert got == want, f"{case['name']}: varredura {n}, {key} = {got}, esperado {want}"
    return image, [(dt, inputs) for dt, inputs, _ in scans], lines


@pytest.mark.parametrize("case", SCAN_CASES, ids=[c["name"] for c in SCAN_CASES])
def test_vector_python(case):
    run_python(case)


@pytest.mark.parametrize("case", SCAN_CASES, ids=[c["name"] for c in SCAN_CASES])
def test_vector_equivalence_c(case, c_vm):
    image, scans, py_lines = run_python(case)
    result = c_vm.run(image, scans)
    assert result.error is None
    for n, (py, c) in enumerate(zip(py_lines, result.lines, strict=True), start=1):
        assert py == c, f"{case['name']}: divergência na varredura {n}\n  py: {py}\n  c : {c}"


def build_error_case(case: dict) -> bytes:
    data = bytearray(encode(assemble("\n".join(case.get("program", ERROR_DOC["base_program"])))))
    if "truncate" in case:
        del data[case["truncate"]:]
    for patch in case.get("patch", []):
        raw = bytes.fromhex(patch["hex"])
        off = patch["offset"] % len(data)
        data[off:off + len(raw)] = raw
    if "append" in case:
        data += bytes.fromhex(case["append"])
    if case.get("fix_crc"):
        struct.pack_into("<I", data, len(data) - 4, crc32(bytes(data[:-4])))
    return bytes(data)


def expected_error(case: dict) -> tuple[int, int] | None:
    if case["expect"] == "OK":
        return None
    return ImageError[case["expect"]].value, case.get("index", -1)


@pytest.mark.parametrize("case", ERROR_DOC["cases"], ids=[c["name"] for c in ERROR_DOC["cases"]])
def test_image_error_python(case):
    data = build_error_case(case)
    want = expected_error(case)
    if want is None:
        decode(data)
        return
    with pytest.raises(ImageValidationError) as info:
        decode(data)
    assert (info.value.code.value, info.value.index) == want


@pytest.mark.parametrize("case", ERROR_DOC["cases"], ids=[c["name"] for c in ERROR_DOC["cases"]])
def test_image_error_c(case, c_vm):
    assert c_vm.run(build_error_case(case), []).error == expected_error(case)
