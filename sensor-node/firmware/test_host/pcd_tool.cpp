/*
 * Command-line wrapper around the C packet code, for poking at packets and
 * sensor frames by hand. Build it with `make tool`. (The receiver's pytest
 * suite compiles its own tiny C program against the same encoder.)
 *
 *   pcd_tool encode <node_id> <seq> <uptime_ms> <temp_centi> <hum_centi> <flags>
 *       prints the 22 packet bytes as hex
 *   pcd_tool decode <hex>
 *       prints "ok <node_id> <seq> <uptime_ms> <temp_centi> <hum_centi> <flags>"
 *       or "error <reason>"
 *   pcd_tool sht31 <12 hex digits>
 *       prints "ok <temp_centi> <hum_centi>" or "error <reason>"
 */
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "pcd_protocol.h"
#include "pcd_sht31.h"

static int hex_to_bytes(const char *hex, uint8_t *out, size_t max_len)
{
    size_t n = std::strlen(hex);
    if (n % 2 != 0 || n / 2 > max_len) {
        return -1;
    }
    for (size_t i = 0; i < n / 2; i++) {
        unsigned value = 0;
        if (std::sscanf(hex + 2 * i, "%2x", &value) != 1) {
            return -1;
        }
        out[i] = (uint8_t)value;
    }
    return (int)(n / 2);
}

int main(int argc, char **argv)
{
    if (argc == 8 && std::strcmp(argv[1], "encode") == 0) {
        pcd_reading_t r;
        uint8_t buf[PCD_PACKET_SIZE];
        r.node_id = (uint32_t)std::strtoul(argv[2], NULL, 0);
        r.seq = (uint32_t)std::strtoul(argv[3], NULL, 0);
        r.uptime_ms = (uint32_t)std::strtoul(argv[4], NULL, 0);
        r.temp_centi_c = (int16_t)std::strtol(argv[5], NULL, 0);
        r.humidity_centi_pct = (uint16_t)std::strtoul(argv[6], NULL, 0);
        r.flags = (uint8_t)std::strtoul(argv[7], NULL, 0);
        if (pcd_packet_encode(&r, buf, sizeof(buf)) != PCD_PACKET_SIZE) {
            return 1;
        }
        for (size_t i = 0; i < sizeof(buf); i++) {
            std::printf("%02x", buf[i]);
        }
        std::printf("\n");
        return 0;
    }
    if (argc == 3 && std::strcmp(argv[1], "decode") == 0) {
        static const char *const reasons[] = {"ok", "arg", "length", "magic", "version", "crc"};
        uint8_t buf[64];
        pcd_reading_t r;
        int n = hex_to_bytes(argv[2], buf, sizeof(buf));
        if (n < 0) {
            std::printf("error hex\n");
            return 0;
        }
        pcd_decode_result_t result = pcd_packet_decode(buf, (size_t)n, &r);
        if (result != PCD_DECODE_OK) {
            std::printf("error %s\n", reasons[result]);
            return 0;
        }
        std::printf("ok %lu %lu %lu %d %u %u\n", (unsigned long)r.node_id, (unsigned long)r.seq,
                    (unsigned long)r.uptime_ms, (int)r.temp_centi_c,
                    (unsigned)r.humidity_centi_pct, (unsigned)r.flags);
        return 0;
    }
    if (argc == 3 && std::strcmp(argv[1], "sht31") == 0) {
        uint8_t frame[PCD_SHT31_FRAME_SIZE];
        int16_t t = 0;
        uint16_t h = 0;
        if (hex_to_bytes(argv[2], frame, sizeof(frame)) != (int)PCD_SHT31_FRAME_SIZE) {
            std::printf("error hex\n");
            return 0;
        }
        switch (pcd_sht31_parse_frame(frame, sizeof(frame), &t, &h)) {
        case PCD_SHT31_OK:
            std::printf("ok %d %u\n", (int)t, (unsigned)h);
            break;
        case PCD_SHT31_BAD_TEMP_CRC:
            std::printf("error temp_crc\n");
            break;
        case PCD_SHT31_BAD_HUMIDITY_CRC:
            std::printf("error humidity_crc\n");
            break;
        default:
            std::printf("error arg\n");
            break;
        }
        return 0;
    }
    std::fprintf(stderr, "usage: pcd_tool encode|decode|sht31 ... (see pcd_tool.cpp)\n");
    return 2;
}
