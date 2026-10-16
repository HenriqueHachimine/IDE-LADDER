#include "ldp_frame.h"

#include <string.h>

#include "lv_crc.h"

enum { ST_SOF0, ST_SOF1, ST_HEADER, ST_PAYLOAD, ST_CRC };

void ldp_parser_init(ldp_parser_t *p)
{
    p->state = ST_SOF0;
    p->pos = 0;
    p->len = 0;
    p->last_ms = 0;
}

int ldp_parser_feed(ldp_parser_t *p, uint8_t b, uint32_t now_ms, ldp_frame_t *out)
{
    if (p->state != ST_SOF0 && (uint32_t)(now_ms - p->last_ms) > LDP_FRAME_TIMEOUT_MS)
        p->state = ST_SOF0;
    p->last_ms = now_ms;

    switch (p->state) {
    case ST_SOF0:
        if (b == LDP_SOF0)
            p->state = ST_SOF1;
        return 0;
    case ST_SOF1:
        if (b == LDP_SOF1) {
            p->state = ST_HEADER;
            p->pos = 0;
        } else if (b != LDP_SOF0) {
            p->state = ST_SOF0;
        }
        return 0;
    case ST_HEADER:
        p->hdr[p->pos++] = b;
        if (p->pos == sizeof(p->hdr)) {
            p->len = (uint16_t)(p->hdr[4] | (p->hdr[5] << 8));
            if (p->len > LDP_MAX_PAYLOAD) {
                p->state = ST_SOF0;
                return 0;
            }
            p->pos = 0;
            p->state = p->len ? ST_PAYLOAD : ST_CRC;
        }
        return 0;
    case ST_PAYLOAD:
        p->payload[p->pos++] = b;
        if (p->pos == p->len) {
            p->pos = 0;
            p->state = ST_CRC;
        }
        return 0;
    case ST_CRC:
    default:
        p->crc[p->pos++] = b;
        if (p->pos < 2)
            return 0;
        p->state = ST_SOF0;
        {
            uint16_t crc = lv_crc16_modbus(0xFFFF, p->hdr, sizeof(p->hdr));
            crc = lv_crc16_modbus(crc, p->payload, p->len);
            if (crc != (uint16_t)(p->crc[0] | (p->crc[1] << 8)) || p->hdr[0] != LDP_VERSION)
                return 0;
        }
        out->type = p->hdr[1];
        out->seq = p->hdr[2];
        out->flags = p->hdr[3];
        out->len = p->len;
        out->payload = p->payload;
        return 1;
    }
}

size_t ldp_encode(uint8_t *buf, size_t cap, uint8_t type, uint8_t seq, uint8_t flags,
                  const uint8_t *payload, uint16_t len)
{
    size_t total = LDP_OVERHEAD + len;
    if (len > LDP_MAX_PAYLOAD || total > cap)
        return 0;
    buf[0] = LDP_SOF0;
    buf[1] = LDP_SOF1;
    buf[2] = LDP_VERSION;
    buf[3] = type;
    buf[4] = seq;
    buf[5] = flags;
    buf[6] = (uint8_t)(len & 0xFF);
    buf[7] = (uint8_t)(len >> 8);
    if (len)
        memmove(buf + LDP_HEADER_BYTES, payload, len);
    uint16_t crc = lv_crc16_modbus(0xFFFF, buf + 2, 6u + len);
    buf[LDP_HEADER_BYTES + len] = (uint8_t)(crc & 0xFF);
    buf[LDP_HEADER_BYTES + len + 1] = (uint8_t)(crc >> 8);
    return total;
}
