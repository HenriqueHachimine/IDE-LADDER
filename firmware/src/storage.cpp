#include "storage.h"

#include <FS.h>
#include <LittleFS.h>

static const char *PROGRAM_PATH = "/prog.bin";
static const char *TEMP_PATH = "/prog.new";

bool storage_begin(void)
{
    return LittleFS.begin(true); /* formata na primeira utilizacao */
}

int storage_load(uint8_t *buf, size_t cap, size_t *len)
{
    if (!LittleFS.exists(PROGRAM_PATH))
        return 1;
    File f = LittleFS.open(PROGRAM_PATH, "r");
    if (!f)
        return -1;
    size_t size = f.size();
    if (size > cap) {
        f.close();
        return -1;
    }
    *len = f.read(buf, size);
    f.close();
    return *len == size ? 0 : -1;
}

static bool matches_file(const char *path, const uint8_t *buf, size_t len)
{
    File f = LittleFS.open(path, "r");
    if (!f)
        return false;
    bool same = f.size() == len;
    uint8_t chunk[128];
    for (size_t pos = 0; same && pos < len;) {
        size_t want = len - pos < sizeof(chunk) ? len - pos : sizeof(chunk);
        same = f.read(chunk, want) == want && memcmp(chunk, buf + pos, want) == 0;
        pos += want;
    }
    f.close();
    return same;
}

int storage_save(const uint8_t *buf, size_t len)
{
    File f = LittleFS.open(TEMP_PATH, "w");
    if (!f)
        return -1;
    size_t written = f.write(buf, len);
    f.close();
    /* close() nao informa erro e o LittleFS so grava de fato ao fechar: confere o que ficou na flash. */
    if (written != len || !matches_file(TEMP_PATH, buf, len)) {
        LittleFS.remove(TEMP_PATH);
        return -1;
    }
    /* lfs_rename substitui o destino de forma atomica. */
    return LittleFS.rename(TEMP_PATH, PROGRAM_PATH) ? 0 : -1;
}
