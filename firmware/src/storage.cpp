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

int storage_save(const uint8_t *buf, size_t len)
{
    File f = LittleFS.open(TEMP_PATH, "w");
    if (!f)
        return -1;
    size_t written = f.write(buf, len);
    f.close();
    if (written != len)
        return -1;
    /* lfs_rename substitui o destino de forma atomica. */
    return LittleFS.rename(TEMP_PATH, PROGRAM_PATH) ? 0 : -1;
}
