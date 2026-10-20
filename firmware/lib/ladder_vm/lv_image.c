#include "lv_image.h"

#include <string.h>

#include "lv_crc.h"

/* Espelha desktop/src/ladderide/core/image.py::decode passo a passo.
 * Qualquer alteracao na ordem das verificacoes deve ser feita nos dois lados
 * e em docs/intermediate-format.md. */

static uint16_t rd16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static uint32_t rd32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint32_t area_size(const lv_program_t *p, uint8_t area)
{
    switch (area) {
    case LV_AREA_I: return p->n_inputs;
    case LV_AREA_Q: return p->n_outputs;
    case LV_AREA_M: return p->n_markers;
    case LV_AREA_S: return LV_SYSTEM_BITS;
    case LV_AREA_T_EN:
    case LV_AREA_T_TT:
    case LV_AREA_T_DN:
    case LV_AREA_TIMER: return p->n_timers;
    case LV_AREA_C_DN:
    case LV_AREA_C_OV:
    case LV_AREA_C_UN:
    case LV_AREA_COUNTER:
    case LV_AREA_C_ACC:
    case LV_AREA_C_PRE: return p->n_counters;
    case LV_AREA_T_ACC:
    case LV_AREA_T_PRE: return p->n_timers;
    case LV_AREA_N: return p->n_words;
    case LV_AREA_K: return p->n_constants;
    case LV_AREA_IW:
    case LV_AREA_QW: return 1;
    default: return 0;
    }
}

static int operand_ok(const lv_program_t *p, lv_operand_class_t cls, uint8_t op, uint8_t area, uint16_t index)
{
    int allowed;
    switch (cls) {
    case LV_OPERAND_NONE:
        return area == LV_AREA_NONE && (index == 0 || op == LV_OP_SOR);
    case LV_OPERAND_BIT_READ:
        allowed = area >= LV_AREA_I && area <= LV_AREA_C_UN;
        break;
    case LV_OPERAND_BIT_WRITE:
        allowed = area == LV_AREA_Q || area == LV_AREA_M;
        break;
    case LV_OPERAND_TIMER:
        allowed = area == LV_AREA_TIMER;
        break;
    case LV_OPERAND_COUNTER:
        allowed = area == LV_AREA_COUNTER;
        break;
    case LV_OPERAND_TIMER_OR_COUNTER:
        allowed = area == LV_AREA_TIMER || area == LV_AREA_COUNTER;
        break;
    case LV_OPERAND_WORD_READ:
        allowed = area >= LV_AREA_N && area <= LV_AREA_QW;
        break;
    case LV_OPERAND_WORD_WRITE:
        allowed = area == LV_AREA_N || area == LV_AREA_QW;
        break;
    default:
        return 0;
    }
    return allowed && index < area_size(p, area);
}

static uint8_t timer_opcode(uint8_t type)
{
    return type == LV_TIMER_TON ? LV_OP_TON : type == LV_TIMER_TOF ? LV_OP_TOF : LV_OP_RTO;
}

#define FAIL(code, idx)              \
    do {                             \
        if (err_index)               \
            *err_index = (idx);      \
        return (code);               \
    } while (0)

lv_image_error_t lv_image_validate(const uint8_t *buf, size_t len, lv_program_t *p, int32_t *err_index)
{
    if (err_index)
        *err_index = -1;
    memset(p, 0, sizeof(*p));

    if (len < LV_HEADER_SIZE)
        FAIL(LV_ERR_TOO_SHORT, -1);
    if (memcmp(buf, LV_FMT_MAGIC, 4) != 0)
        FAIL(LV_ERR_BAD_MAGIC, -1);
    if (buf[4] != LV_FMT_MAJOR || buf[5] > LV_FMT_MINOR)
        FAIL(LV_ERR_UNSUPPORTED_VERSION, -1);
    if (rd16(buf + 6) != LV_HEADER_SIZE)
        FAIL(LV_ERR_BAD_HEADER_SIZE, -1);
    uint32_t total = rd32(buf + 8);
    if (total != len)
        FAIL(LV_ERR_SIZE_MISMATCH, -1);
    if (len > LV_MAX_IMAGE_SIZE)
        FAIL(LV_ERR_LIMIT_EXCEEDED, -1);
    uint32_t stored_crc = rd32(buf + len - LV_CRC_SIZE);
    if (lv_crc32(0, buf, len - LV_CRC_SIZE) != stored_crc)
        FAIL(LV_ERR_BAD_CRC, -1);
    if (rd32(buf + 28) != 0)
        FAIL(LV_ERR_RESERVED_NONZERO, -1);

    p->n_inputs = buf[12];
    p->n_outputs = buf[13];
    p->n_markers = rd16(buf + 14);
    p->n_timers = buf[16];
    p->n_counters = buf[17];
    p->n_rungs = rd16(buf + 18);
    p->n_instr = rd16(buf + 20);
    p->safe_outputs = rd16(buf + 22);
    p->build_id = rd32(buf + 24);
    p->n_words = rd16(buf + 32);
    p->n_constants = rd16(buf + 34);
    p->crc = stored_crc;

    if (p->n_inputs > LV_MAX_INPUTS || p->n_outputs > LV_MAX_OUTPUTS || p->n_markers > LV_MAX_MARKERS ||
        p->n_timers > LV_MAX_TIMERS || p->n_counters > LV_MAX_COUNTERS || p->n_rungs > LV_MAX_RUNGS ||
        p->n_instr > LV_MAX_INSTRUCTIONS || p->n_words > LV_MAX_WORDS || p->n_constants > LV_MAX_CONSTANTS)
        FAIL(LV_ERR_LIMIT_EXCEEDED, -1);
    uint32_t expected = LV_HEADER_SIZE + (uint32_t)p->n_timers * LV_TIMER_ENTRY_SIZE +
                        (uint32_t)p->n_counters * LV_COUNTER_ENTRY_SIZE +
                        (uint32_t)p->n_constants * LV_CONSTANT_ENTRY_SIZE +
                        (uint32_t)p->n_instr * LV_INSTRUCTION_SIZE + LV_CRC_SIZE;
    if (expected != total)
        FAIL(LV_ERR_SIZE_MISMATCH, -1);
    if ((uint32_t)p->safe_outputs >> p->n_outputs)
        FAIL(LV_ERR_RESERVED_NONZERO, -1);

    const uint8_t *e = buf + LV_HEADER_SIZE;
    for (unsigned i = 0; i < p->n_timers; i++, e += LV_TIMER_ENTRY_SIZE) {
        uint32_t preset = rd32(e + 4);
        if (e[0] > LV_TIMER_RTO || e[1] || e[2] || e[3] || preset > LV_MAX_PRESET)
            FAIL(LV_ERR_BAD_TIMER_TABLE, -1);
        p->timer_type[i] = e[0];
        p->timer_preset[i] = preset;
    }
    for (unsigned i = 0; i < p->n_counters; i++, e += LV_COUNTER_ENTRY_SIZE) {
        uint32_t preset = rd32(e + 4);
        if (e[0] > LV_COUNTER_DOWN || e[1] || e[2] || e[3] || preset > LV_MAX_PRESET)
            FAIL(LV_ERR_BAD_COUNTER_TABLE, -1);
        p->counter_type[i] = e[0];
        p->counter_preset[i] = (int32_t)preset;
    }
    for (unsigned i = 0; i < p->n_constants; i++, e += LV_CONSTANT_ENTRY_SIZE)
        p->constants[i] = (int32_t)rd32(e);
    p->code = e;

    int in_rung = 0;
    uint32_t rung = 0;
    unsigned depth = 0;
    uint8_t timer_driven[LV_MAX_TIMERS] = {0};
    uint8_t counter_driven[LV_MAX_COUNTERS] = {0};
    uint8_t pending_op = 0;   /* instrucao cujos operandos ARG ainda faltam */
    unsigned pending_k = 0, pending_n = 0;
    for (uint16_t i = 0; i < p->n_instr; i++) {
        uint8_t op = lv_instr_op(p, i);
        uint8_t area = lv_instr_area(p, i);
        uint16_t index = lv_instr_index(p, i);
        if (lv_operand_class(op) == LV_OPERAND_INVALID)
            FAIL(LV_ERR_BAD_OPCODE, i);
        if (in_rung == (op == LV_OP_SOR))
            FAIL(LV_ERR_BAD_STRUCTURE, i);
        if ((pending_k < pending_n) != (op == LV_OP_ARG))
            FAIL(LV_ERR_BAD_STRUCTURE, i);
        lv_operand_class_t cls = op == LV_OP_ARG ? lv_arg_class(pending_op, pending_k++) : lv_operand_class(op);
        if (!operand_ok(p, cls, op, area, index))
            FAIL(LV_ERR_BAD_OPERAND, i);
        if (op != LV_OP_ARG) {
            pending_op = op;
            pending_k = 0;
            pending_n = lv_arg_count(op);
        }
        switch (op) {
        case LV_OP_SOR:
            if (index != rung || rung >= p->n_rungs)
                FAIL(LV_ERR_BAD_STRUCTURE, i);
            in_rung = 1;
            depth = 0;
            break;
        case LV_OP_EOR:
            if (depth != 0)
                FAIL(LV_ERR_BRANCH_ERROR, i);
            in_rung = 0;
            rung++;
            break;
        case LV_OP_BST:
            if (depth >= LV_MAX_BRANCH_DEPTH)
                FAIL(LV_ERR_BRANCH_ERROR, i);
            depth++;
            break;
        case LV_OP_NXB:
        case LV_OP_BND:
            if (depth == 0)
                FAIL(LV_ERR_BRANCH_ERROR, i);
            if (op == LV_OP_BND)
                depth--;
            break;
        case LV_OP_TON:
        case LV_OP_TOF:
        case LV_OP_RTO:
            if (timer_opcode(p->timer_type[index]) != op)
                FAIL(LV_ERR_TYPE_MISMATCH, i);
            if (timer_driven[index])
                FAIL(LV_ERR_DUPLICATE_DRIVER, i);
            timer_driven[index] = 1;
            break;
        case LV_OP_CTU:
        case LV_OP_CTD:
            if ((p->counter_type[index] == LV_COUNTER_UP ? LV_OP_CTU : LV_OP_CTD) != op)
                FAIL(LV_ERR_TYPE_MISMATCH, i);
            if (counter_driven[index])
                FAIL(LV_ERR_DUPLICATE_DRIVER, i);
            counter_driven[index] = 1;
            break;
        default:
            break;
        }
    }
    if (in_rung || rung != p->n_rungs)
        FAIL(LV_ERR_BAD_STRUCTURE, (int32_t)p->n_instr);
    return LV_ERR_OK;
}
