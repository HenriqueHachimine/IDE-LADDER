#ifndef LV_IMAGE_H
#define LV_IMAGE_H

#include <stddef.h>
#include <stdint.h>

#include "ladder_isa.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Visao validada de uma imagem LDRB. `code` aponta para dentro do buffer
 * original, que deve permanecer valido enquanto o programa estiver em uso. */
typedef struct {
    uint8_t n_inputs;
    uint8_t n_outputs;
    uint16_t n_markers;
    uint16_t n_words;
    uint16_t n_constants;
    uint8_t n_timers;
    uint8_t n_counters;
    uint16_t n_rungs;
    uint16_t n_instr;
    uint16_t safe_outputs;
    uint32_t build_id;
    uint32_t crc;
    uint8_t timer_type[LV_MAX_TIMERS];
    uint32_t timer_preset[LV_MAX_TIMERS];
    uint8_t counter_type[LV_MAX_COUNTERS];
    int32_t counter_preset[LV_MAX_COUNTERS];
    int32_t constants[LV_MAX_CONSTANTS];
    const uint8_t *code; /* n_instr * 4 bytes: opcode, area, index (u16 LE) */
} lv_program_t;

/* Valida `buf` seguindo exatamente a ordem normativa de
 * docs/intermediate-format.md. Em caso de erro, `*err_index` recebe o indice da
 * instrucao (ou -1 se o erro nao for de codigo). `out` so e confiavel com LV_ERR_OK. */
lv_image_error_t lv_image_validate(const uint8_t *buf, size_t len, lv_program_t *out, int32_t *err_index);

static inline uint8_t lv_instr_op(const lv_program_t *p, uint16_t i) { return p->code[4u * i]; }
static inline uint8_t lv_instr_area(const lv_program_t *p, uint16_t i) { return p->code[4u * i + 1u]; }
static inline uint16_t lv_instr_index(const lv_program_t *p, uint16_t i)
{
    return (uint16_t)(p->code[4u * i + 2u] | (p->code[4u * i + 3u] << 8));
}

#ifdef __cplusplus
}
#endif

#endif /* LV_IMAGE_H */
