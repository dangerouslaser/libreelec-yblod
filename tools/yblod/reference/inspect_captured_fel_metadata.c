/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "dvbridge_placebo.h"
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>

int main(int argc, char **argv)
{
    if (argc != 4)
        return 2;
    unsigned char *data[3] = {0};
    bool valid[3] = {0}, residual[3] = {0};
    int status = 1;
    for (int i = 0; i < 3; ++i) {
        FILE *file = fopen(argv[i + 1], "rb");
        struct stat st;
        if (!file || fstat(fileno(file), &st) || !S_ISREG(st.st_mode) ||
            st.st_size <= 0 || st.st_size > 1048576) {
            if (file)
                fclose(file);
            goto done;
        }
        const size_t size = (size_t)st.st_size;
        data[i] = malloc(size);
        if (!data[i]) {
            fclose(file);
            goto done;
        }
        const size_t read = fread(data[i], 1, size, file);
        const bool failed = ferror(file) || read != size || fgetc(file) != EOF;
        fclose(file);
        if (failed)
            goto done;
        struct dvbridge_color color = {0};
        valid[i] = dvbridge_map_color(&color, data[i], size, true);
        residual[i] = valid[i] && color.dovi.nlq_active;
    }
    status = valid[0] && valid[1] && valid[2] && residual[0] && residual[1] && residual[2] ? 0 : 1;
done:
    printf("{\"pass\":%s,\"metadata\":[", status ? "false" : "true");
    for (int i = 0; i < 3; ++i) {
        printf("%s{\"frame\":%d,\"actual_map_color_valid\":%s,"
               "\"metadata_uses_enhancement_residual\":%s}", i ? "," : "", i + 1,
               valid[i] ? "true" : "false", residual[i] ? "true" : "false");
        free(data[i]);
    }
    puts("]}");
    return status;
}
