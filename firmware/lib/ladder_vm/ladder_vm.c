#include "ladder_vm.h"

#include <string.h>

static void counter_reset(lv_counter_t *c, uint8_t type, int32_t preset)
{
    if (type == LV_COUNTER_UP) {
        c->acc = 0;
        c->dn = c->acc >= preset;
    } else {
        c->acc = preset;
        c->dn = c->acc <= 0;
    }
    c->ov = 0;
    c->un = 0;
}

void lv_vm_init(lv_vm_t *vm, const lv_program_t *prog)
{
    memset(vm, 0, sizeof(*vm));
    vm->prog = prog;
    lv_vm_reset(vm);
}

void lv_vm_reset(lv_vm_t *vm)
{
    const lv_program_t *p = vm->prog;
    memset(vm->i, 0, sizeof(vm->i));
    memset(vm->q, 0, sizeof(vm->q));
    memset(vm->m, 0, sizeof(vm->m));
    memset(vm->timers, 0, sizeof(vm->timers));
    memset(vm->counters, 0, sizeof(vm->counters));
    memset(vm->power, 0, sizeof(vm->power));
    for (unsigned k = 0; k < p->n_counters; k++)
        counter_reset(&vm->counters[k], p->counter_type[k], p->counter_preset[k]);
    vm->scan_count = 0;
    vm->dt = 0;
    vm->sec_phase = 0;
    vm->first_scan = 1;
    vm->rlo = 0;
    vm->sp = 0;
}

static int system_bit(const lv_vm_t *vm, uint16_t index)
{
    switch (index) {
    case LV_SYS_FIRST_SCAN: return vm->first_scan;
    case LV_SYS_ALWAYS_ON: return 1;
    case LV_SYS_CLOCK_1S: return vm->sec_phase < 500u;
    default: return 0;
    }
}

int lv_vm_read_bit(const lv_vm_t *vm, uint8_t area, uint16_t index)
{
    switch (area) {
    case LV_AREA_I: return vm->i[index];
    case LV_AREA_Q: return vm->q[index];
    case LV_AREA_M: return vm->m[index];
    case LV_AREA_S: return system_bit(vm, index);
    case LV_AREA_T_EN: return vm->timers[index].en;
    case LV_AREA_T_TT: return vm->timers[index].tt;
    case LV_AREA_T_DN: return vm->timers[index].dn;
    case LV_AREA_C_DN: return vm->counters[index].dn;
    case LV_AREA_C_OV: return vm->counters[index].ov;
    case LV_AREA_C_UN: return vm->counters[index].un;
    default: return 0;
    }
}

static void write_bit(lv_vm_t *vm, uint8_t area, uint16_t index, uint8_t value)
{
    if (area == LV_AREA_Q)
        vm->q[index] = value;
    else
        vm->m[index] = value;
}

/* acc + dt limitado a pre, sem estouro de 32 bits. */
static uint32_t sat_add(uint32_t acc, uint32_t dt, uint32_t pre)
{
    return dt >= pre - acc ? pre : acc + dt;
}

static void exec_timer(lv_vm_t *vm, uint8_t op, lv_timer_t *t, uint32_t pre)
{
    uint8_t rlo = vm->rlo;
    uint8_t prev = t->en;
    t->en = rlo;
    if (op == LV_OP_TON) {
        if (rlo) {
            if (prev && !t->dn)
                t->acc = sat_add(t->acc, vm->dt, pre);
            t->dn = t->acc >= pre;
            t->tt = !t->dn;
        } else {
            t->acc = 0;
            t->dn = 0;
            t->tt = 0;
        }
    } else if (op == LV_OP_TOF) {
        if (rlo) {
            t->acc = 0;
            t->dn = 1;
            t->tt = 0;
        } else if (t->dn) {
            if (!prev)
                t->acc = sat_add(t->acc, vm->dt, pre);
            if (t->acc >= pre) {
                t->dn = 0;
                t->tt = 0;
            } else {
                t->tt = 1;
            }
        } else {
            t->tt = 0;
        }
    } else { /* RTO */
        if (rlo) {
            if (prev && !t->dn)
                t->acc = sat_add(t->acc, vm->dt, pre);
            t->dn = t->acc >= pre;
            t->tt = !t->dn;
        } else {
            t->tt = 0;
        }
    }
}

static void exec_counter(lv_vm_t *vm, uint8_t op, lv_counter_t *c, int32_t pre)
{
    uint8_t edge = vm->rlo && !c->prev;
    c->prev = vm->rlo;
    if (op == LV_OP_CTU) {
        if (edge) {
            if (c->acc == INT32_MAX)
                c->ov = 1;
            else
                c->acc++;
        }
        c->dn = c->acc >= pre;
    } else {
        if (edge) {
            if (c->acc == INT32_MIN)
                c->un = 1;
            else
                c->acc--;
        }
        c->dn = c->acc <= 0;
    }
}

static void execute(lv_vm_t *vm, uint8_t op, uint8_t area, uint16_t index)
{
    const lv_program_t *p = vm->prog;
    switch (op) {
    case LV_OP_SOR:
        vm->rlo = 1;
        vm->sp = 0;
        break;
    case LV_OP_EOR:
        break;
    case LV_OP_XIC:
        vm->rlo = vm->rlo && lv_vm_read_bit(vm, area, index);
        break;
    case LV_OP_XIO:
        vm->rlo = vm->rlo && !lv_vm_read_bit(vm, area, index);
        break;
    case LV_OP_NOT:
        vm->rlo = !vm->rlo;
        break;
    case LV_OP_BST:
        /* A validacao garante sp < LV_MAX_BRANCH_DEPTH; o teste evita corrupcao
         * de memoria caso a VM seja usada com um programa nao validado. */
        if (vm->sp < LV_MAX_BRANCH_DEPTH) {
            vm->stack_entry[vm->sp] = vm->rlo;
            vm->stack_acc[vm->sp] = 0;
            vm->sp++;
        }
        break;
    case LV_OP_NXB:
        if (vm->sp > 0) {
            vm->stack_acc[vm->sp - 1] |= vm->rlo;
            vm->rlo = vm->stack_entry[vm->sp - 1];
        }
        break;
    case LV_OP_BND:
        if (vm->sp > 0) {
            vm->sp--;
            vm->rlo = vm->stack_acc[vm->sp] | vm->rlo;
        }
        break;
    case LV_OP_OTE:
        write_bit(vm, area, index, vm->rlo);
        break;
    case LV_OP_OTL:
        if (vm->rlo)
            write_bit(vm, area, index, 1);
        break;
    case LV_OP_OTU:
        if (vm->rlo)
            write_bit(vm, area, index, 0);
        break;
    case LV_OP_TON:
    case LV_OP_TOF:
    case LV_OP_RTO:
        exec_timer(vm, op, &vm->timers[index], p->timer_preset[index]);
        break;
    case LV_OP_CTU:
    case LV_OP_CTD:
        exec_counter(vm, op, &vm->counters[index], p->counter_preset[index]);
        break;
    case LV_OP_RES:
        if (!vm->rlo)
            break;
        if (area == LV_AREA_TIMER)
            memset(&vm->timers[index], 0, sizeof(lv_timer_t));
        else
            counter_reset(&vm->counters[index], p->counter_type[index], p->counter_preset[index]);
        break;
    default:
        break;
    }
}

uint16_t lv_vm_outputs(const lv_vm_t *vm)
{
    uint16_t out = 0;
    for (unsigned k = 0; k < vm->prog->n_outputs; k++)
        if (vm->q[k])
            out |= (uint16_t)(1u << k);
    return out;
}

uint16_t lv_vm_scan(lv_vm_t *vm, uint16_t inputs, uint32_t dt_ms)
{
    const lv_program_t *p = vm->prog;

    /* Fases 1-2: imagem de entradas e base de tempo congeladas para a varredura. */
    vm->dt = vm->first_scan ? 0u : dt_ms;
    if (!vm->first_scan)
        vm->sec_phase = (vm->sec_phase + vm->dt % 1000u) % 1000u;
    for (unsigned k = 0; k < p->n_inputs; k++)
        vm->i[k] = (uint8_t)((inputs >> k) & 1u);

    /* Fases 3-5: avaliacao sequencial das redes. */
    for (uint16_t pc = 0; pc < p->n_instr; pc++) {
        execute(vm, lv_instr_op(p, pc), lv_instr_area(p, pc), lv_instr_index(p, pc));
        if (vm->rlo)
            vm->power[pc >> 3] |= (uint8_t)(1u << (pc & 7u));
        else
            vm->power[pc >> 3] &= (uint8_t)~(1u << (pc & 7u));
    }

    vm->first_scan = 0;
    vm->scan_count++;
    return lv_vm_outputs(vm);
}

int lv_vm_power(const lv_vm_t *vm, uint16_t instr)
{
    return (vm->power[instr >> 3] >> (instr & 7u)) & 1u;
}
