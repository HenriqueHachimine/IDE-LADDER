/* Firmware CLP LADDER para ESP32 8 reles.
 *
 * Tarefas:
 *   scan  (nucleo 1, prioridade alta): plc_scan a cada SCAN_PERIOD_MS com vTaskDelayUntil
 *   loop  (nucleo 1, prioridade normal): protocolo LDP na USB e Modbus RTU no RS-485
 * Todo acesso ao estado do CLP passa pelo mesmo mutex. */
#include <Arduino.h>
#include <esp_log.h>
#include <esp_timer.h>

#include "board_config.h"
#include "io_board.h"
#include "storage.h"

extern "C" {
#include "modbus_rtu.h"
#include "plc_runtime.h"
}

static plc_t plc;
static mb_rtu_t modbus;
static SemaphoreHandle_t plc_lock;

/* ----------------------------------------------------------------- HAL */
static uint16_t pending_outputs;

static uint16_t hal_read_inputs(void *)
{
    /* Ler as entradas exige deslocar 8 bits; reenviamos as saidas atuais para
     * que os reles nao mudem durante a leitura. */
    return io_board_transfer(pending_outputs);
}

static void hal_write_outputs(void *, uint16_t mask)
{
    pending_outputs = mask;
    io_board_transfer(mask); /* aplica imediatamente (STOP/FAULT nao esperam a proxima varredura) */
}

static int hal_load(void *, uint8_t *buf, size_t cap, size_t *len) { return storage_load(buf, cap, len); }
static int hal_save(void *, const uint8_t *buf, size_t len) { return storage_save(buf, len); }
static void hal_send(void *, const uint8_t *data, size_t len) { Serial.write(data, len); }
static uint64_t hal_micros(void *) { return (uint64_t)esp_timer_get_time(); }

/* -------------------------------------------------------------- tarefas */
static void scan_task(void *)
{
    TickType_t last = xTaskGetTickCount();
    for (;;) {
        xSemaphoreTake(plc_lock, portMAX_DELAY);
        plc_scan(&plc);
        xSemaphoreGive(plc_lock);
        vTaskDelayUntil(&last, pdMS_TO_TICKS(SCAN_PERIOD_MS));
    }
}

void setup()
{
    io_board_begin(); /* reles desligados antes de tudo */
    esp_log_level_set("*", ESP_LOG_NONE);

    Serial.setRxBufferSize(4096);
    Serial.begin(LDP_BAUD);
    Serial.setDebugOutput(false);

    bool fs_ok = storage_begin();

    static const plc_hal_t hal = {hal_read_inputs, hal_write_outputs, hal_load, hal_save,
                                  hal_send, hal_micros, nullptr};
    plc_config_t cfg = {};
    cfg.n_inputs = BOARD_INPUTS;
    cfg.n_outputs = BOARD_OUTPUTS;
    cfg.scan_period_ms = SCAN_PERIOD_MS;
    cfg.watchdog_us = SCAN_WATCHDOG_US;
    cfg.autorun = AUTORUN_ON_BOOT;
    cfg.allow_sim_inputs = 0;
    cfg.fw_version = FW_VERSION;
    cfg.hw_id = HW_ID;
    plc_lock = xSemaphoreCreateMutex();
    plc_init(&plc, &hal, &cfg);
    if (!fs_ok && plc.state != PLC_STATE_FAULT) {
        plc.state = PLC_STATE_FAULT;
        plc.fault = PLC_FAULT_INTERNAL;
    }

#if MODBUS_ENABLED
    pinMode(PIN_RS485_DE, OUTPUT);
    digitalWrite(PIN_RS485_DE, LOW);
    Serial2.begin(MODBUS_BAUD, SERIAL_8N1, PIN_RS485_RX, PIN_RS485_TX);
    mb_init(&modbus, MODBUS_ADDRESS, MODBUS_BAUD);
#endif

    xTaskCreatePinnedToCore(scan_task, "plc_scan", 6144, nullptr, configMAX_PRIORITIES - 2, nullptr, 1);
}

void loop()
{
    static uint8_t buf[256];
    size_t n = 0;
    while (Serial.available() && n < sizeof(buf))
        buf[n++] = (uint8_t)Serial.read();
    xSemaphoreTake(plc_lock, portMAX_DELAY);
    if (n)
        plc_rx(&plc, buf, n);
    plc_poll(&plc);
    xSemaphoreGive(plc_lock);

#if MODBUS_ENABLED
    while (Serial2.available())
        mb_rx_byte(&modbus, (uint8_t)Serial2.read(), (uint64_t)esp_timer_get_time());
    static uint8_t reply[260];
    xSemaphoreTake(plc_lock, portMAX_DELAY);
    size_t len = mb_poll(&modbus, (uint64_t)esp_timer_get_time(), &plc, reply, sizeof(reply));
    xSemaphoreGive(plc_lock);
    if (len) {
        digitalWrite(PIN_RS485_DE, HIGH);
        Serial2.write(reply, len);
        Serial2.flush();
        digitalWrite(PIN_RS485_DE, LOW);
    }
#endif
    if (!n)
        vTaskDelay(1);
}
