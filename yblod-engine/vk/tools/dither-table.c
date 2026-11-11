/* Prints yblod/dither_blue64.h, SDR output's dither pattern: libplacebo's
 * blue noise (yblod/placebo/dither.c, pl_generate_blue_noise, the matrix of
 * pl_dither_default_params) at 64 x 64, as its ranks 0..4095.
 *
 * The generator breaks ties with rand() and builds its kernel with exp() and
 * log(): its result belongs to the C library it ran with. The table in the
 * repository is the one output this tool gave (glibc, the build host's dev
 * container) and is what the engine and its CPU reference both use; run it
 * again only to see where the table came from, not to replace it (a
 * different table changes every SDR golden hash).
 *
 *   cc -Iyblod/placebo -Iyblod/placebo/include tools/dither-table.c -lm && ./a.out > yblod/dither_blue64.h
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include "../yblod/placebo/dither.c"

/* dither.c's two allocator calls, without libplacebo's allocator */
void *pl_zalloc(void *parent, size_t size)
{
    (void)parent;
    return calloc(1, size);
}

void pl_free(void *p)
{
    free(p);
}

int main(void)
{
    enum { N = 64 };
    static float data[N * N];
    static unsigned char seen[N * N];
    pl_generate_blue_noise(data, N);
    printf("/* libplacebo's 64 x 64 blue noise as ranks (tools/dither-table.c). Generated: do not edit. */\n");
    for (int i = 0; i < N * N; i++) {
        int rank = (int)lroundf(data[i] * (N * N));
        if (rank < 0 || rank >= N * N || seen[rank]++)
            return fprintf(stderr, "not a permutation at %d\n", i), 1;
        printf("%d,%s", rank, i % 16 == 15 ? "\n" : " ");
    }
    return 0;
}
