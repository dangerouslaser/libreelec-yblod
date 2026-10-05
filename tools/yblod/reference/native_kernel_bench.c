#define _POSIX_C_SOURCE 200809L
#include "native_composer.h"
#include <stddef.h>
#include <stdint.h>
#include <time.h>

/* Diagnostic caller-owned buffers, not a new playback API. Link this file and
 * native_composer.c as separate translation units without LTO. One warm-up and
 * final checksum are outside the timed interval. The actual public chunk API,
 * including its validation, is executed on every iteration. */
struct yb_kernel_measurement {
    double wall_seconds;
    double cpu_seconds;
    uint64_t processed_samples;
    uint64_t checksum;
};

uint64_t yb_sizeof_kernel_measurement(void)
{
    return sizeof(struct yb_kernel_measurement);
}

static double difference(struct timespec end, struct timespec start)
{
    return (double)(end.tv_sec - start.tv_sec) +
           (double)(end.tv_nsec - start.tv_nsec) / 1000000000.0;
}

static uint64_t checksum_word(uint64_t hash, uint32_t word)
{
    for (unsigned shift = 0; shift < 32; shift += 8) {
        hash ^= (uint64_t)((word >> shift) & UINT32_C(255));
        hash *= UINT64_C(1099511628211);
    }
    return hash;
}

int yb_kernel_benchmark(const struct yb_mapping_config *map,
                        const struct yb_nlq_config *nlq, int32_t component,
                        const uint16_t *y, const uint16_t *cb, const uint16_t *cr,
                        const uint16_t *el, uint32_t count, int32_t enabled,
                        int32_t output_depth, uint16_t *mapped, int32_t *residual,
                        int32_t *sum, uint16_t *reconstructed, uint32_t iterations,
                        struct yb_kernel_measurement *measurement)
{
    if (!measurement || iterations == 0 || iterations > 4096 ||
        count == 0 || count > 65536 ||
        (uint64_t)count * iterations > UINT64_C(100000000))
        return YB_INVALID_ARGUMENT;
    int status = yb_process_chunk(map, nlq, component, y, cb, cr, el, count,
                                  enabled, output_depth, mapped, residual, sum, reconstructed);
    if (status != YB_OK)
        return status;
    struct timespec wall_start, cpu_start, wall_end, cpu_end;
    if (clock_gettime(CLOCK_MONOTONIC, &wall_start) != 0 ||
        clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &cpu_start) != 0)
        return 100;
    for (uint32_t iteration = 0; iteration < iterations; ++iteration) {
        status = yb_process_chunk(map, nlq, component, y, cb, cr, el, count,
                                  enabled, output_depth, mapped, residual, sum, reconstructed);
        if (status != YB_OK)
            return status;
    }
    if (clock_gettime(CLOCK_PROCESS_CPUTIME_ID, &cpu_end) != 0 ||
        clock_gettime(CLOCK_MONOTONIC, &wall_end) != 0)
        return 100;
    uint64_t hash = UINT64_C(14695981039346656037);
    for (uint32_t index = 0; index < count; ++index) {
        hash = checksum_word(hash, mapped[index]);
        hash = checksum_word(hash, (uint32_t)residual[index]);
        hash = checksum_word(hash, (uint32_t)sum[index]);
        hash = checksum_word(hash, reconstructed[index]);
    }
    struct yb_kernel_measurement result = {
        difference(wall_end, wall_start), difference(cpu_end, cpu_start),
        (uint64_t)count * iterations, hash
    };
    *measurement = result;
    return YB_OK;
}
