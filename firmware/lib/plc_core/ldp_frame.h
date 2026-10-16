#ifndef LDP_FRAME_H
#define LDP_FRAME_H

#include <stddef.h>
#include <stdint.h>

#include "ldp_protocol.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Quadro LDP:  A5 5A | ver | type | seq | flags | len16 LE | payload | crc16 LE
 * CRC-16/MODBUS sobre ver..payload. Ver docs/communication-protocol.md. */

#define LDP_HEADER_BYTES 8u   /* SOF(2) + ver,type,seq,flags + len(2) */
#define LDP_OVERHEAD (LDP_HEADER_BYTES + 2u)

typedef struct {
    uint8_t type;
    uint8_t seq;
    uint8_t flags;
    uint16_t len;
    const uint8_t *payload;
} ldp_frame_t;

typedef struct {
    uint8_t state;
    uint8_t hdr[6];
    uint16_t pos;
    uint16_t len;
    uint8_t crc[2];
    uint32_t last_ms;
    uint8_t payload[LDP_MAX_PAYLOAD];
} ldp_parser_t;

void ldp_parser_init(ldp_parser_t *p);

/* Alimenta um byte. Retorna 1 quando um quadro valido termina (dados em *out,
 * validos ate a proxima chamada). Lixo, CRC errado, versao diferente ou pausa
 * maior que LDP_FRAME_TIMEOUT_MS no meio de um quadro sao descartados. */
int ldp_parser_feed(ldp_parser_t *p, uint8_t byte, uint32_t now_ms, ldp_frame_t *out);

/* Monta um quadro em buf (capacidade cap). Retorna o tamanho ou 0 se nao couber. */
size_t ldp_encode(uint8_t *buf, size_t cap, uint8_t type, uint8_t seq, uint8_t flags,
                  const uint8_t *payload, uint16_t len);

#ifdef __cplusplus
}
#endif

#endif /* LDP_FRAME_H */
