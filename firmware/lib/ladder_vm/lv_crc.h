#ifndef LV_CRC_H
#define LV_CRC_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* CRC-32/ISO-HDLC (zlib). Para calculo incremental, passe o resultado anterior
 * como `crc`; comece com 0. check("123456789") = 0xCBF43926. */
uint32_t lv_crc32(uint32_t crc, const uint8_t *data, size_t len);

/* CRC-16/MODBUS. Comece com 0xFFFF. check("123456789") = 0x4B37. */
uint16_t lv_crc16_modbus(uint16_t crc, const uint8_t *data, size_t len);

#ifdef __cplusplus
}
#endif

#endif /* LV_CRC_H */
