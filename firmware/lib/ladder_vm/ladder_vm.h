#ifndef LADDER_VM_H
#define LADDER_VM_H

#include <stdint.h>

#include "ladder_isa.h"
#include "lv_image.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Interpretador LADDER do firmware. Semantica normativa em
 * docs/ladder-specification.md; equivalente a desktop/src/ladderide/core/vm.py.
 *
 * Pre-condicao: o programa passou por lv_image_validate(). A VM nao aloca
 * memoria dinamica e nao conhece relogio: o tempo entra por `dt_ms`. */

typedef struct {
    uint32_t acc; /* ms acumulados, 0..preset */
    uint8_t en, tt, dn;
} lv_timer_t;

typedef struct {
    int32_t acc;
    uint8_t dn, ov, un;
    uint8_t prev; /* memoria de borda */
} lv_counter_t;

typedef struct {
    const lv_program_t *prog;
    uint8_t i[LV_MAX_INPUTS];
    uint8_t q[LV_MAX_OUTPUTS];
    uint8_t m[LV_MAX_MARKERS];
    lv_timer_t timers[LV_MAX_TIMERS];
    lv_counter_t counters[LV_MAX_COUNTERS];
    int32_t n[LV_MAX_WORDS];                      /* registradores N */
    uint8_t math_ov, math_zero, math_sign;        /* S0.4..S0.6 */
    uint8_t power[(LV_MAX_INSTRUCTIONS + 7) / 8]; /* RLO apos cada instrucao */
    uint32_t scan_count;
    uint32_t dt;
    uint32_t sec_phase;
    uint8_t first_scan;
    uint8_t rlo;
    uint8_t sp;
    uint8_t stack_entry[LV_MAX_BRANCH_DEPTH];
    uint8_t stack_acc[LV_MAX_BRANCH_DEPTH];
} lv_vm_t;

/* Associa o programa e faz a partida a frio. */
void lv_vm_init(lv_vm_t *vm, const lv_program_t *prog);
/* Partida a frio: zera I/Q/M, temporizadores e reinicia contadores. */
void lv_vm_reset(lv_vm_t *vm);
/* Executa uma varredura completa e devolve a mascara de saidas (bit k = Qk). */
uint16_t lv_vm_scan(lv_vm_t *vm, uint16_t inputs, uint32_t dt_ms);
uint16_t lv_vm_outputs(const lv_vm_t *vm);
int lv_vm_read_bit(const lv_vm_t *vm, uint8_t area, uint16_t index);
int32_t lv_vm_read_word(const lv_vm_t *vm, uint8_t area, uint16_t index);
int lv_vm_power(const lv_vm_t *vm, uint16_t instr);

#ifdef __cplusplus
}
#endif

#endif /* LADDER_VM_H */
