/* Testes unitarios em C do parser LDP e do escravo Modbus RTU (rodam no PC).
 * Imprime "OK <n>" e sai com 0 se tudo passar. */
#include <stdio.h>
#include <string.h>

#include "lv_crc.h"
#include "ldp_frame.h"
#include "modbus_rtu.h"

static int failures, checks;
#define CHECK(cond)                                                       \
    do {                                                                  \
        checks++;                                                         \
        if (!(cond)) {                                                    \
            failures++;                                                   \
            fprintf(stderr, "FALHA %s:%d: %s\n", __FILE__, __LINE__, #cond); \
        }                                                                 \
    } while (0)

static ldp_parser_t parser;

static int feed_all(const uint8_t *data, size_t n, uint32_t t0, uint32_t step, ldp_frame_t *out)
{
    int got = 0;
    for (size_t k = 0; k < n; k++)
        got += ldp_parser_feed(&parser, data[k], t0 + (uint32_t)k * step, out);
    return got;
}

static void test_frames(void)
{
    uint8_t buf[64], payload[3] = {1, 2, 3};
    ldp_frame_t f;
    size_t n = ldp_encode(buf, sizeof(buf), 0x21, 7, 0, payload, 3);
    CHECK(n == 13);

    ldp_parser_init(&parser);
    CHECK(feed_all(buf, n, 0, 1, &f) == 1);
    CHECK(f.type == 0x21 && f.seq == 7 && f.len == 3 && memcmp(f.payload, payload, 3) == 0);

    /* lixo antes (inclui um SOF0 solto) e quadro sem payload */
    uint8_t stream[80] = {0x00, 0xA5, 0x13, 0xA5, 0xA5};
    size_t m = ldp_encode(stream + 5, sizeof(stream) - 5, 0x02, 9, 0, NULL, 0);
    ldp_parser_init(&parser);
    CHECK(feed_all(stream, 5 + m, 100, 1, &f) == 1 && f.type == 0x02 && f.len == 0);

    /* CRC errado e descartado; o proximo quadro ainda e reconhecido */
    uint8_t bad[64];
    memcpy(bad, buf, n);
    bad[n - 1] ^= 0xFF;
    ldp_parser_init(&parser);
    CHECK(feed_all(bad, n, 0, 1, &f) == 0);
    CHECK(feed_all(buf, n, 50, 1, &f) == 1);

    /* pausa maior que o timeout no meio do quadro: descartado */
    ldp_parser_init(&parser);
    CHECK(feed_all(buf, 6, 0, 1, &f) == 0);
    CHECK(feed_all(buf + 6, n - 6, 1000, 1, &f) == 0);
    CHECK(feed_all(buf, n, 2000, 1, &f) == 1);

    /* comprimento acima do maximo e rejeitado no cabecalho */
    uint8_t huge[] = {0xA5, 0x5A, 1, 1, 0, 0, 0xFF, 0xFF};
    ldp_parser_init(&parser);
    CHECK(feed_all(huge, sizeof(huge), 0, 1, &f) == 0 && parser.state == 0);

    /* versao diferente: ignorado */
    uint8_t other[64];
    memcpy(other, buf, n);
    other[2] = 2;
    uint16_t crc = lv_crc16_modbus(0xFFFF, other + 2, n - 4);
    other[n - 2] = (uint8_t)crc;
    other[n - 1] = (uint8_t)(crc >> 8);
    ldp_parser_init(&parser);
    CHECK(feed_all(other, n, 0, 1, &f) == 0);

    CHECK(ldp_encode(buf, 10, 1, 1, 0, payload, 3) == 0); /* nao cabe */
}

static size_t mb_req(uint8_t *out, uint8_t addr, uint8_t fc, uint16_t start, uint16_t qty)
{
    out[0] = addr;
    out[1] = fc;
    out[2] = (uint8_t)(start >> 8);
    out[3] = (uint8_t)start;
    out[4] = (uint8_t)(qty >> 8);
    out[5] = (uint8_t)qty;
    uint16_t crc = lv_crc16_modbus(0xFFFF, out, 6);
    out[6] = (uint8_t)crc;
    out[7] = (uint8_t)(crc >> 8);
    return 8;
}

static int crc_ok(const uint8_t *r, size_t n)
{
    uint16_t crc = lv_crc16_modbus(0xFFFF, r, n - 2);
    return n >= 4 && r[n - 2] == (uint8_t)crc && r[n - 1] == (uint8_t)(crc >> 8);
}

static plc_t plc;

static void test_modbus(void)
{
    uint8_t req[16], resp[260];
    memset(&plc, 0, sizeof(plc));
    plc.cfg.n_inputs = 8;
    plc.cfg.n_outputs = 8;
    plc.inputs = 0x05;
    plc.state = 0;

    size_t n = mb_process(11, req, mb_req(req, 11, 2, 0, 8), &plc, resp, sizeof(resp));
    CHECK(n == 6 && resp[1] == 2 && resp[2] == 1 && resp[3] == 0x05 && crc_ok(resp, n));

    n = mb_process(11, req, mb_req(req, 11, 2, 1, 2), &plc, resp, sizeof(resp));
    CHECK(n == 6 && resp[3] == 0x02); /* I0.1=0, I0.2=1 */

    n = mb_process(11, req, mb_req(req, 11, 2, 4, 8), &plc, resp, sizeof(resp));
    CHECK(n == 5 && resp[1] == 0x82 && resp[2] == 2); /* fora da faixa */

    n = mb_process(11, req, mb_req(req, 11, 4, 0, 3), &plc, resp, sizeof(resp));
    CHECK(n == 11 && resp[2] == 6 && resp[3] == 0 && resp[4] == 0 && crc_ok(resp, n));

    n = mb_process(11, req, mb_req(req, 11, 4, 100, 2), &plc, resp, sizeof(resp));
    CHECK(n == 5 && resp[1] == 0x84 && resp[2] == 2); /* sem programa: sem temporizadores */

    n = mb_process(11, req, mb_req(req, 11, 6, 0, 1), &plc, resp, sizeof(resp));
    CHECK(n == 5 && resp[1] == 0x86 && resp[2] == 1); /* escrita nao suportada */

    n = mb_process(11, req, mb_req(req, 12, 2, 0, 8), &plc, resp, sizeof(resp));
    CHECK(n == 0); /* outro endereco */

    mb_req(req, 11, 2, 0, 8);
    req[7] ^= 1;
    CHECK(mb_process(11, req, 8, &plc, resp, sizeof(resp)) == 0); /* CRC errado */

    /* delimitacao por silencio */
    mb_rtu_t mb;
    mb_init(&mb, 11, 9600);
    CHECK(mb.t35_us > 3900 && mb.t35_us < 4100);
    mb_req(req, 11, 2, 0, 8);
    for (int k = 0; k < 8; k++)
        mb_rx_byte(&mb, req[k], 1000u + (uint64_t)k * 1000u);
    CHECK(mb_poll(&mb, 8500, &plc, resp, sizeof(resp)) == 0);      /* ainda dentro de t3,5 */
    CHECK(mb_poll(&mb, 8000 + 4200, &plc, resp, sizeof(resp)) == 6);
}

int main(void)
{
    test_frames();
    test_modbus();
    if (failures) {
        printf("FALHOU %d de %d\n", failures, checks);
        return 1;
    }
    printf("OK %d\n", checks);
    return 0;
}
