/* SHT31 checksum and unit conversion. See pcd_sht31.h. */
#include "pcd_sht31.h"

uint8_t pcd_sht31_crc8(const uint8_t *data, size_t len)
{
    uint8_t crc = 0xFFu;
    size_t i;
    int bit;

    if (data == NULL) {
        return crc;
    }
    for (i = 0; i < len; i++) {
        crc = (uint8_t)(crc ^ data[i]);
        for (bit = 0; bit < 8; bit++) {
            if (crc & 0x80u) {
                crc = (uint8_t)((crc << 1) ^ 0x31u);
            } else {
                crc = (uint8_t)(crc << 1);
            }
        }
    }
    return crc;
}

/* Integer maths on purpose: the result is exact and identical on the ESP32
 * and on the PC running the tests. Adding half the divisor (32767) before
 * dividing rounds to nearest instead of always rounding down. The largest
 * intermediate value is 17500 * 65535 + 32767, which fits in 32 bits. */
int16_t pcd_sht31_temp_centi_c(uint16_t raw)
{
    uint32_t scaled = (17500u * (uint32_t)raw + 32767u) / 65535u; /* 0..17500 */
    return (int16_t)((int32_t)scaled - 4500);
}

uint16_t pcd_sht31_humidity_centi_pct(uint16_t raw)
{
    return (uint16_t)((10000u * (uint32_t)raw + 32767u) / 65535u);
}

pcd_sht31_result_t pcd_sht31_parse_frame(const uint8_t *frame, size_t len, int16_t *temp_centi_c,
                                         uint16_t *humidity_centi_pct)
{
    uint16_t raw_temp;
    uint16_t raw_humidity;

    if (frame == NULL || temp_centi_c == NULL || humidity_centi_pct == NULL ||
        len != PCD_SHT31_FRAME_SIZE) {
        return PCD_SHT31_BAD_ARG;
    }
    if (pcd_sht31_crc8(&frame[0], 2) != frame[2]) {
        return PCD_SHT31_BAD_TEMP_CRC;
    }
    if (pcd_sht31_crc8(&frame[3], 2) != frame[5]) {
        return PCD_SHT31_BAD_HUMIDITY_CRC;
    }
    raw_temp = (uint16_t)(((uint16_t)frame[0] << 8) | frame[1]);
    raw_humidity = (uint16_t)(((uint16_t)frame[3] << 8) | frame[4]);
    *temp_centi_c = pcd_sht31_temp_centi_c(raw_temp);
    *humidity_centi_pct = pcd_sht31_humidity_centi_pct(raw_humidity);
    return PCD_SHT31_OK;
}
