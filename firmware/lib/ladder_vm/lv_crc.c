#include "lv_crc.h"

/* Implementacoes bit a bit: sem tabelas, para economizar RAM/flash.
 * O custo (~8 iteracoes por byte) e irrelevante para imagens de poucos KiB. */

uint32_t lv_crc32(uint32_t crc, const uint8_t *data, size_t len)
{
    crc = ~crc;
    while (len--) {
        crc ^= *data++;
        for (int k = 0; k < 8; k++) {
            crc = (crc & 1u) ? (crc >> 1) ^ 0xEDB88320u : crc >> 1;
        }
    }
    return ~crc;
}

uint16_t lv_crc16_modbus(uint16_t crc, const uint8_t *data, size_t len)
{
    while (len--) {
        crc ^= *data++;
        for (int k = 0; k < 8; k++) {
            crc = (crc & 1u) ? (uint16_t)((crc >> 1) ^ 0xA001u) : (uint16_t)(crc >> 1);
        }
    }
    return crc;
}
