#include "modbus_rtu.h"

#include <string.h>

#include "lv_crc.h"

void mb_init(mb_rtu_t *mb, uint8_t addr, uint32_t baud)
{
    memset(mb, 0, sizeof(*mb));
    mb->addr = addr;
    /* 1 caractere = 11 bits; acima de 19200 bps a norma fixa 1750 us. */
    mb->t35_us = baud > 19200u ? 1750u : (uint32_t)(3.5 * 11.0 * 1e6 / baud);
}

void mb_rx_byte(mb_rtu_t *mb, uint8_t byte, uint64_t now_us)
{
    if (mb->len && now_us - mb->last_byte_us >= mb->t35_us) {
        mb->len = 0; /* quadro anterior incompleto/abandonado */
        mb->overflow = 0;
    }
    if (mb->len < sizeof(mb->buf))
        mb->buf[mb->len++] = byte;
    else
        mb->overflow = 1;
    mb->last_byte_us = now_us;
}

size_t mb_poll(mb_rtu_t *mb, uint64_t now_us, const plc_t *plc, uint8_t *out, size_t cap)
{
    if (!mb->len || now_us - mb->last_byte_us < mb->t35_us)
        return 0;
    size_t n = mb->overflow ? 0 : mb_process(mb->addr, mb->buf, mb->len, plc, out, cap);
    mb->len = 0;
    mb->overflow = 0;
    return n;
}

static size_t finish(uint8_t *out, size_t n)
{
    uint16_t crc = lv_crc16_modbus(0xFFFF, out, n);
    out[n] = (uint8_t)(crc & 0xFF);
    out[n + 1] = (uint8_t)(crc >> 8);
    return n + 2;
}

static size_t exception(uint8_t addr, uint8_t fc, uint8_t code, uint8_t *out)
{
    out[0] = addr;
    out[1] = (uint8_t)(fc | 0x80u);
    out[2] = code;
    return finish(out, 3);
}

static int input_register(const plc_t *plc, uint16_t reg, uint16_t *value)
{
    const lv_program_t *p = &plc->prog;
    if (reg == 0) {
        *value = plc->state;
        return 1;
    }
    if (reg == 1 || reg == 2) {
        uint32_t sc = plc->has_program ? plc->vm.scan_count : 0;
        *value = (uint16_t)(reg == 1 ? sc >> 16 : sc & 0xFFFF);
        return 1;
    }
    if (reg >= 100 && reg < 100 + 2u * LV_MAX_TIMERS) {
        unsigned n = (reg - 100u) / 2u;
        if (!plc->has_program || n >= p->n_timers)
            return 0;
        uint32_t acc = plc->vm.timers[n].acc;
        *value = (uint16_t)((reg - 100u) % 2u == 0 ? acc >> 16 : acc & 0xFFFF);
        return 1;
    }
    if (reg >= 200 && reg < 200 + 2u * LV_MAX_COUNTERS) {
        unsigned n = (reg - 200u) / 2u;
        if (!plc->has_program || n >= p->n_counters)
            return 0;
        uint32_t acc = (uint32_t)plc->vm.counters[n].acc;
        *value = (uint16_t)((reg - 200u) % 2u == 0 ? acc >> 16 : acc & 0xFFFF);
        return 1;
    }
    return 0;
}

size_t mb_process(uint8_t addr, const uint8_t *req, size_t len, const plc_t *plc, uint8_t *out, size_t cap)
{
    if (len < 4 || cap < 256)
        return 0;
    uint16_t crc = lv_crc16_modbus(0xFFFF, req, len - 2);
    if (crc != (uint16_t)(req[len - 2] | (req[len - 1] << 8)))
        return 0;           /* CRC invalido: silencio, conforme a norma */
    if (req[0] != addr)
        return 0;           /* outro escravo ou broadcast (sem resposta para leituras) */
    uint8_t fc = req[1];
    if (fc != 1 && fc != 2 && fc != 4)
        return exception(addr, fc, 1, out);
    if (len != 8)
        return exception(addr, fc, 3, out);
    uint16_t start = (uint16_t)((req[2] << 8) | req[3]);
    uint16_t qty = (uint16_t)((req[4] << 8) | req[5]);
    out[0] = addr;
    out[1] = fc;
    if (fc == 1 || fc == 2) {
        uint16_t bits = fc == 1 ? (plc->has_program ? lv_vm_outputs(&plc->vm) : 0) : plc->inputs;
        unsigned limit = fc == 1 ? plc->cfg.n_outputs : plc->cfg.n_inputs;
        if (qty == 0 || qty > 2000)
            return exception(addr, fc, 3, out);
        if ((unsigned)start + qty > limit)
            return exception(addr, fc, 2, out);
        uint8_t nbytes = (uint8_t)((qty + 7) / 8);
        out[2] = nbytes;
        memset(out + 3, 0, nbytes);
        for (unsigned k = 0; k < qty; k++)
            if (bits >> (start + k) & 1u)
                out[3 + k / 8] |= (uint8_t)(1u << (k % 8));
        return finish(out, 3u + nbytes);
    }
    if (qty == 0 || qty > 125)
        return exception(addr, fc, 3, out);
    out[2] = (uint8_t)(2 * qty);
    for (unsigned k = 0; k < qty; k++) {
        uint16_t v;
        if (!input_register(plc, (uint16_t)(start + k), &v))
            return exception(addr, fc, 2, out);
        out[3 + 2 * k] = (uint8_t)(v >> 8);
        out[4 + 2 * k] = (uint8_t)(v & 0xFF);
    }
    return finish(out, 3u + 2u * qty);
}
