"""Checksums usados no formato LDRB e no protocolo de comunicacao.

As implementacoes C equivalentes ficam em firmware/lib/ladder_vm/lv_crc.c e sao
verificadas contra os mesmos valores de referencia nos testes.
"""
from __future__ import annotations

import zlib


def crc32(data: bytes) -> int:
    """CRC-32/ISO-HDLC (o mesmo do zlib/Ethernet). check("123456789") = 0xCBF43926."""
    return zlib.crc32(data) & 0xFFFFFFFF


def crc16_modbus(data: bytes) -> int:
    """CRC-16/MODBUS (poly 0xA001 refletido, init 0xFFFF). check("123456789") = 0x4B37."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc
