#include "plc_runtime.h"

#include <string.h>

#include "lv_crc.h"

#define PLC_PROTOCOL_LIMIT_MS LDP_LOAD_SESSION_TIMEOUT_MS

/* ------------------------------------------------------------ utilitarios */
static void put16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
}

static void put32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}

static uint16_t get16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static uint32_t get32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint64_t now_us(const plc_t *plc) { return plc->hal.micros(plc->hal.ctx); }
static uint32_t now_ms(const plc_t *plc) { return (uint32_t)(now_us(plc) / 1000u); }

uint16_t plc_safe_outputs(const plc_t *plc)
{
    return plc->has_program ? plc->prog.safe_outputs : 0u;
}

static void enter_fault(plc_t *plc, uint8_t fault)
{
    plc->state = PLC_STATE_FAULT;
    plc->fault = fault;
    plc->q_commanded = plc_safe_outputs(plc);
    plc->hal.write_outputs(plc->hal.ctx, plc->q_commanded);
}

/* Ativa a imagem em plc->active_buf (ja copiada). Retorna 0 se valida. */
static int activate(plc_t *plc, size_t len)
{
    int32_t idx;
    plc->active_len = len;
    if (lv_image_validate(plc->active_buf, len, &plc->prog, &idx) != LV_ERR_OK ||
        plc->prog.n_inputs > plc->cfg.n_inputs || plc->prog.n_outputs > plc->cfg.n_outputs) {
        plc->has_program = 0;
        return -1;
    }
    plc->has_program = 1;
    lv_vm_init(&plc->vm, &plc->prog);
    plc->test_mode = 0;
    return 0;
}

/* ------------------------------------------------------------- iniciacao */
void plc_init(plc_t *plc, const plc_hal_t *hal, const plc_config_t *cfg)
{
    memset(plc, 0, sizeof(*plc));
    plc->hal = *hal;
    plc->cfg = *cfg;
    plc->last_seq = -1;
    plc->state = PLC_STATE_STOP;
    plc->boot_us = now_us(plc);
    ldp_parser_init(&plc->parser);

    /* Saidas no estado seguro antes de qualquer outra coisa. */
    plc->hal.write_outputs(plc->hal.ctx, 0);

    size_t len = 0;
    int rc = plc->hal.storage_load(plc->hal.ctx, plc->active_buf, sizeof(plc->active_buf), &len);
    if (rc == 0) {
        if (activate(plc, len) != 0) {
            enter_fault(plc, PLC_FAULT_PROGRAM_CORRUPT);
            return;
        }
        if (plc->cfg.autorun) {
            plc->state = PLC_STATE_RUN;
            plc->run_first = 1;
        }
    } else if (rc < 0) {
        enter_fault(plc, PLC_FAULT_PROGRAM_CORRUPT);
        return;
    }
    plc->q_commanded = plc_safe_outputs(plc);
    plc->hal.write_outputs(plc->hal.ctx, plc->q_commanded);
}

/* ------------------------------------------------------------- varredura */
void plc_scan(plc_t *plc)
{
    uint64_t t0 = now_us(plc);
    uint16_t raw = plc->sim_inputs_active ? plc->sim_inputs : plc->hal.read_inputs(plc->hal.ctx);
    plc->inputs = (uint16_t)(raw & ((1u << plc->cfg.n_inputs) - 1u));

    if (plc->last_scan_us) {
        uint64_t interval = t0 - plc->last_scan_us;
        if (interval > plc->max_interval_us)
            plc->max_interval_us = (uint32_t)interval;
        if (interval > 2u * 1000u * plc->cfg.scan_period_ms)
            plc->overruns++;
    }

    if (plc->state == PLC_STATE_RUN) {
        uint32_t dt_ms = 0;
        if (plc->run_first) {
            plc->run_first = 0;
            plc->rem_us = 0;
        } else {
            uint64_t total = (t0 - plc->last_scan_us) + plc->rem_us;
            uint64_t ms = total / 1000u;
            dt_ms = ms > 0xFFFFFFFFu ? 0xFFFFFFFFu : (uint32_t)ms;
            plc->rem_us = (uint32_t)(total % 1000u);
        }
        plc->q_logical = lv_vm_scan(&plc->vm, plc->inputs, dt_ms);
        plc->q_commanded = plc->q_logical;
    } else {
        plc->q_commanded = plc_safe_outputs(plc);
    }
    plc->hal.write_outputs(plc->hal.ctx, plc->q_commanded);
    plc->last_scan_us = t0;

    uint32_t exec = (uint32_t)(now_us(plc) - t0);
    plc->last_exec_us = exec;
    if (exec > plc->max_exec_us)
        plc->max_exec_us = exec;
    if (plc->state == PLC_STATE_RUN && exec > plc->cfg.watchdog_us)
        enter_fault(plc, PLC_FAULT_SCAN_TIMEOUT);
}

void plc_poll(plc_t *plc)
{
    if (plc->state == PLC_STATE_PROGRAM_LOADING &&
        (uint32_t)(now_ms(plc) - plc->load_last_ms) > PLC_PROTOCOL_LIMIT_MS)
        plc->state = PLC_STATE_STOP; /* staging descartado; programa ativo intacto */
}

/* ------------------------------------------------------------ instantaneo */
size_t plc_snapshot(const plc_t *plc, uint8_t *b, size_t cap)
{
    const lv_program_t *p = &plc->prog;
    unsigned nm = plc->has_program ? p->n_markers : 0;
    unsigned nt = plc->has_program ? p->n_timers : 0;
    unsigned nc = plc->has_program ? p->n_counters : 0;
    unsigned ni = plc->has_program ? p->n_instr : 0;
    unsigned nw = plc->has_program ? p->n_words : 0;
    size_t need = 22 + 2 + (nm + 7) / 8 + 1 + 5u * nt + 1 + 5u * nc + 2 + (ni + 7) / 8 + 1 + 4u * nw + 1;
    if (need > cap)
        return 0;
    size_t o = 0;
    b[o++] = plc->state;
    b[o++] = plc->fault;
    put32(b + o, plc->has_program ? plc->vm.scan_count : 0);
    o += 4;
    put16(b + o, plc->inputs);
    o += 2;
    put16(b + o, plc->has_program ? lv_vm_outputs(&plc->vm) : 0);
    o += 2;
    put16(b + o, plc->q_commanded);
    o += 2;
    put32(b + o, plc->has_program ? p->build_id : 0);
    o += 4;
    put32(b + o, plc->has_program ? p->crc : 0);
    o += 4;
    b[o++] = plc->test_mode;
    b[o++] = 0; /* reservado */
    put16(b + o, (uint16_t)nm);
    o += 2;
    for (unsigned k = 0; k < (nm + 7) / 8; k++) {
        uint8_t byte = 0;
        for (unsigned j = 0; j < 8 && 8 * k + j < nm; j++)
            byte |= (uint8_t)((plc->vm.m[8 * k + j] ? 1u : 0u) << j);
        b[o++] = byte;
    }
    b[o++] = (uint8_t)nt;
    for (unsigned k = 0; k < nt; k++) {
        const lv_timer_t *t = &plc->vm.timers[k];
        put32(b + o, t->acc);
        b[o + 4] = (uint8_t)(t->en | t->tt << 1 | t->dn << 2);
        o += 5;
    }
    b[o++] = (uint8_t)nc;
    for (unsigned k = 0; k < nc; k++) {
        const lv_counter_t *c = &plc->vm.counters[k];
        put32(b + o, (uint32_t)c->acc);
        b[o + 4] = (uint8_t)(c->dn | c->ov << 1 | c->un << 2 | c->prev << 3);
        o += 5;
    }
    put16(b + o, (uint16_t)ni);
    o += 2;
    memcpy(b + o, plc->vm.power, (ni + 7) / 8);
    o += (ni + 7) / 8;
    /* LDRB 2: registradores N e bits de estado da matematica (S0.4..S0.6) */
    b[o++] = (uint8_t)nw;
    for (unsigned k = 0; k < nw; k++) {
        put32(b + o, (uint32_t)plc->vm.n[k]);
        o += 4;
    }
    b[o++] = plc->has_program ? (uint8_t)(plc->vm.math_ov | plc->vm.math_zero << 1 | plc->vm.math_sign << 2) : 0;
    return o;
}

/* ------------------------------------------------------------- protocolo */
static void send_frame(plc_t *plc, uint8_t type, uint8_t seq, uint8_t flags, const uint8_t *data, uint16_t len)
{
    plc->last_resp_len = ldp_encode(plc->last_resp, sizeof(plc->last_resp), (uint8_t)(type | LDP_RESPONSE_FLAG),
                                    seq, flags, data, len);
    plc->last_seq = seq;
    plc->last_type = type;
    plc->hal.send(plc->hal.ctx, plc->last_resp, plc->last_resp_len);
}

static void reply(plc_t *plc, const ldp_frame_t *f, uint16_t len)
{
    send_frame(plc, f->type, f->seq, 0, plc->payload, len);
}

static void reply_error(plc_t *plc, const ldp_frame_t *f, uint8_t code, const uint8_t *detail, uint16_t dlen)
{
    uint8_t buf[16];
    buf[0] = code;
    if (dlen > sizeof(buf) - 1)
        dlen = sizeof(buf) - 1;
    if (dlen)
        memcpy(buf + 1, detail, dlen);
    send_frame(plc, f->type, f->seq, LDP_ERROR_FLAG, buf, (uint16_t)(1 + dlen));
}

static uint16_t put_str(uint8_t *b, const char *s)
{
    size_t n = s ? strlen(s) : 0;
    if (n > 40)
        n = 40;
    b[0] = (uint8_t)n;
    memcpy(b + 1, s, n);
    return (uint16_t)(1 + n);
}

static void cmd_info(plc_t *plc, const ldp_frame_t *f)
{
    uint8_t *b = plc->payload;
    b[0] = LDP_VERSION;
    b[1] = LV_FMT_MAJOR;
    b[2] = LV_FMT_MINOR;
    b[3] = plc->cfg.n_inputs;
    b[4] = plc->cfg.n_outputs;
    put16(b + 5, (uint16_t)LV_MAX_IMAGE_SIZE);
    put16(b + 7, (uint16_t)LDP_MAX_CHUNK);
    put16(b + 9, plc->cfg.scan_period_ms);
    uint16_t o = 11;
    o = (uint16_t)(o + put_str(b + o, plc->cfg.fw_version));
    o = (uint16_t)(o + put_str(b + o, plc->cfg.hw_id));
    reply(plc, f, o);
}

static void cmd_status(plc_t *plc, const ldp_frame_t *f)
{
    uint8_t *b = plc->payload;
    b[0] = plc->state;
    b[1] = plc->fault;
    b[2] = plc->has_program;
    b[3] = plc->test_mode;
    put32(b + 4, plc->has_program ? plc->prog.build_id : 0);
    put32(b + 8, plc->has_program ? plc->prog.crc : 0);
    put32(b + 12, plc->has_program ? plc->vm.scan_count : 0);
    put32(b + 16, plc->last_exec_us);
    put32(b + 20, plc->max_exec_us);
    put32(b + 24, plc->overruns);
    put32(b + 28, (uint32_t)((now_us(plc) - plc->boot_us) / 1000u));
    put16(b + 32, plc->cfg.scan_period_ms);
    put32(b + 34, plc->max_interval_us);
    reply(plc, f, 38);
}

static void cmd_set_mode(plc_t *plc, const ldp_frame_t *f)
{
    if (f->len != 1)
        return reply_error(plc, f, LDP_ERR_BAD_LENGTH, 0, 0);
    uint8_t mode = f->payload[0];
    if (plc->state == PLC_STATE_FAULT)
        return reply_error(plc, f, LDP_ERR_FAULT_ACTIVE, 0, 0);
    if (plc->state == PLC_STATE_PROGRAM_LOADING)
        return reply_error(plc, f, LDP_ERR_BAD_STATE, 0, 0);
    if (mode == 1) {
        if (!plc->has_program)
            return reply_error(plc, f, LDP_ERR_NO_PROGRAM, 0, 0);
        if (plc->state != PLC_STATE_RUN) {
            lv_vm_reset(&plc->vm); /* partida a frio */
            plc->test_mode = 0;
            plc->run_first = 1;
            plc->max_exec_us = 0;
            plc->overruns = 0;
            plc->max_interval_us = 0;
            plc->state = PLC_STATE_RUN;
        }
    } else if (mode == 0) {
        plc->state = PLC_STATE_STOP;
        plc->q_commanded = plc_safe_outputs(plc);
        plc->hal.write_outputs(plc->hal.ctx, plc->q_commanded);
    } else {
        return reply_error(plc, f, LDP_ERR_BAD_ARGUMENT, 0, 0);
    }
    plc->payload[0] = plc->state;
    reply(plc, f, 1);
}

static void cmd_load_begin(plc_t *plc, const ldp_frame_t *f)
{
    if (f->len != 8)
        return reply_error(plc, f, LDP_ERR_BAD_LENGTH, 0, 0);
    if (plc->state == PLC_STATE_FAULT)
        return reply_error(plc, f, LDP_ERR_FAULT_ACTIVE, 0, 0);
    if (plc->state != PLC_STATE_STOP && plc->state != PLC_STATE_PROGRAM_LOADING)
        return reply_error(plc, f, LDP_ERR_BAD_STATE, 0, 0);
    uint32_t size = get32(f->payload);
    if (size > LV_MAX_IMAGE_SIZE)
        return reply_error(plc, f, LDP_ERR_LOAD_TOO_LARGE, 0, 0);
    if (size < LV_HEADER_SIZE + LV_CRC_SIZE)
        return reply_error(plc, f, LDP_ERR_BAD_ARGUMENT, 0, 0);
    plc->load_size = size;
    plc->load_crc = get32(f->payload + 4);
    plc->load_received = 0;
    plc->load_validated = 0;
    plc->load_last_ms = now_ms(plc);
    plc->test_mode = 0;
    plc->state = PLC_STATE_PROGRAM_LOADING;
    put16(plc->payload, (uint16_t)LDP_MAX_CHUNK);
    reply(plc, f, 2);
}

static void cmd_load_chunk(plc_t *plc, const ldp_frame_t *f)
{
    if (plc->state != PLC_STATE_PROGRAM_LOADING)
        return reply_error(plc, f, LDP_ERR_BAD_STATE, 0, 0);
    if (f->len < 4 || f->len - 4u > LDP_MAX_CHUNK)
        return reply_error(plc, f, LDP_ERR_BAD_LENGTH, 0, 0);
    uint32_t offset = get32(f->payload);
    uint32_t n = f->len - 4u;
    plc->load_last_ms = now_ms(plc);
    if (offset + n > plc->load_size)
        return reply_error(plc, f, LDP_ERR_BAD_OFFSET, 0, 0);
    if (offset == plc->load_received) {
        memcpy(plc->staging + offset, f->payload + 4, n);
        plc->load_received += n;
        plc->load_validated = 0;
    } else if (offset + n != plc->load_received) { /* repeticao do ultimo bloco e aceita */
        uint8_t d[4];
        put32(d, plc->load_received);
        return reply_error(plc, f, LDP_ERR_BAD_OFFSET, d, 4);
    }
    put32(plc->payload, plc->load_received);
    reply(plc, f, 4);
}

static void cmd_load_end(plc_t *plc, const ldp_frame_t *f)
{
    if (plc->state != PLC_STATE_PROGRAM_LOADING)
        return reply_error(plc, f, LDP_ERR_BAD_STATE, 0, 0);
    plc->load_last_ms = now_ms(plc);
    if (plc->load_received != plc->load_size)
        return reply_error(plc, f, LDP_ERR_BAD_OFFSET, 0, 0);
    if (lv_crc32(0, plc->staging, plc->load_size) != plc->load_crc)
        return reply_error(plc, f, LDP_ERR_IMAGE_CRC, 0, 0);
    static lv_program_t check;
    int32_t idx;
    lv_image_error_t err = lv_image_validate(plc->staging, plc->load_size, &check, &idx);
    if (err != LV_ERR_OK) {
        uint8_t d[5];
        d[0] = (uint8_t)err;
        put32(d + 1, (uint32_t)idx);
        return reply_error(plc, f, LDP_ERR_IMAGE_INVALID, d, 5);
    }
    if (check.n_inputs > plc->cfg.n_inputs || check.n_outputs > plc->cfg.n_outputs)
        return reply_error(plc, f, LDP_ERR_INCOMPATIBLE, 0, 0);
    plc->load_validated = 1;
    reply(plc, f, 0);
}

static void cmd_load_commit(plc_t *plc, const ldp_frame_t *f)
{
    if (plc->state != PLC_STATE_PROGRAM_LOADING || !plc->load_validated)
        return reply_error(plc, f, LDP_ERR_BAD_STATE, 0, 0);
    if (plc->hal.storage_save(plc->hal.ctx, plc->staging, plc->load_size) != 0) {
        plc->state = PLC_STATE_STOP;
        return reply_error(plc, f, LDP_ERR_STORAGE, 0, 0);
    }
    memcpy(plc->active_buf, plc->staging, plc->load_size);
    plc->state = PLC_STATE_STOP;
    if (activate(plc, plc->load_size) != 0) { /* nao deveria ocorrer: ja validado */
        enter_fault(plc, PLC_FAULT_INTERNAL);
        return reply_error(plc, f, LDP_ERR_IMAGE_INVALID, 0, 0);
    }
    plc->fault = PLC_FAULT_NONE;
    put32(plc->payload, plc->prog.build_id);
    put32(plc->payload + 4, plc->prog.crc);
    reply(plc, f, 8);
}

static void cmd_read_io(plc_t *plc, const ldp_frame_t *f)
{
    plc->payload[0] = plc->state;
    put16(plc->payload + 1, plc->inputs);
    put16(plc->payload + 3, plc->has_program ? lv_vm_outputs(&plc->vm) : 0);
    put16(plc->payload + 5, plc->q_commanded);
    reply(plc, f, 7);
}

static void cmd_test_scan(plc_t *plc, const ldp_frame_t *f)
{
    if (f->len != 6)
        return reply_error(plc, f, LDP_ERR_BAD_LENGTH, 0, 0);
    if (plc->state != PLC_STATE_STOP || !plc->test_mode)
        return reply_error(plc, f, LDP_ERR_BAD_STATE, 0, 0);
    /* Executa a VM com entradas e dt fornecidos; as saidas fisicas continuam no
     * estado seguro porque o dispositivo permanece em STOP. */
    lv_vm_scan(&plc->vm, get16(f->payload), get32(f->payload + 2));
    reply(plc, f, (uint16_t)plc_snapshot(plc, plc->payload, sizeof(plc->payload)));
}

static void dispatch(plc_t *plc, const ldp_frame_t *f)
{
    if (f->flags & LDP_ERROR_FLAG || f->type & LDP_RESPONSE_FLAG)
        return; /* nao e um pedido */
    if (f->seq == plc->last_seq && f->type == plc->last_type && plc->last_resp_len) {
        plc->hal.send(plc->hal.ctx, plc->last_resp, plc->last_resp_len); /* retransmissao */
        return;
    }
    switch (f->type) {
    case LDP_CMD_INFO:
        return cmd_info(plc, f);
    case LDP_CMD_STATUS:
        return cmd_status(plc, f);
    case LDP_CMD_SET_MODE:
        return cmd_set_mode(plc, f);
    case LDP_CMD_CLEAR_FAULT:
        if (plc->state == PLC_STATE_FAULT) {
            plc->state = PLC_STATE_STOP;
            plc->fault = PLC_FAULT_NONE;
        }
        plc->payload[0] = plc->state;
        return reply(plc, f, 1);
    case LDP_CMD_LOAD_BEGIN:
        return cmd_load_begin(plc, f);
    case LDP_CMD_LOAD_CHUNK:
        return cmd_load_chunk(plc, f);
    case LDP_CMD_LOAD_END:
        return cmd_load_end(plc, f);
    case LDP_CMD_LOAD_COMMIT:
        return cmd_load_commit(plc, f);
    case LDP_CMD_LOAD_ABORT:
        if (plc->state == PLC_STATE_PROGRAM_LOADING)
            plc->state = PLC_STATE_STOP;
        plc->payload[0] = plc->state;
        return reply(plc, f, 1);
    case LDP_CMD_READ_IO:
        return cmd_read_io(plc, f);
    case LDP_CMD_READ_VARS:
        return reply(plc, f, (uint16_t)plc_snapshot(plc, plc->payload, sizeof(plc->payload)));
    case LDP_CMD_WRITE_MARKER:
        if (f->len != 3)
            return reply_error(plc, f, LDP_ERR_BAD_LENGTH, 0, 0);
        if (!plc->has_program)
            return reply_error(plc, f, LDP_ERR_NO_PROGRAM, 0, 0);
        if (get16(f->payload) >= plc->prog.n_markers || f->payload[2] > 1)
            return reply_error(plc, f, LDP_ERR_BAD_ARGUMENT, 0, 0);
        plc->vm.m[get16(f->payload)] = f->payload[2];
        return reply(plc, f, 0);
    case LDP_CMD_TEST_BEGIN:
        if (plc->state != PLC_STATE_STOP)
            return reply_error(plc, f, LDP_ERR_BAD_STATE, 0, 0);
        if (!plc->has_program)
            return reply_error(plc, f, LDP_ERR_NO_PROGRAM, 0, 0);
        lv_vm_reset(&plc->vm);
        plc->test_mode = 1;
        return reply(plc, f, 0);
    case LDP_CMD_TEST_SCAN:
        return cmd_test_scan(plc, f);
    case LDP_CMD_SIM_SET_INPUTS:
        if (!plc->cfg.allow_sim_inputs)
            break;
        if (f->len != 2)
            return reply_error(plc, f, LDP_ERR_BAD_LENGTH, 0, 0);
        plc->sim_inputs = get16(f->payload);
        plc->sim_inputs_active = 1;
        return reply(plc, f, 0);
    default:
        break;
    }
    reply_error(plc, f, LDP_ERR_UNKNOWN_COMMAND, 0, 0);
}

void plc_rx(plc_t *plc, const uint8_t *data, size_t len)
{
    uint32_t ms = now_ms(plc);
    ldp_frame_t f;
    for (size_t k = 0; k < len; k++)
        if (ldp_parser_feed(&plc->parser, data[k], ms, &f))
            dispatch(plc, &f);
}
