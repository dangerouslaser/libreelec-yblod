/* SPDX-License-Identifier: GPL-3.0-or-later */
#define ff_hevc_qsv_decoder fixture_hevc_qsv_decoder
#include "qsvdec.c"
#include <assert.h>
#include <stdio.h>
int main(void)
{
    QSVDecContext s={.class=(AVClass*)&hevc_qsv_class};
    AVCodecContext avctx={.priv_data=&s,.codec_id=AV_CODEC_ID_HEVC};
    av_opt_set_defaults(&s); assert(!s.qsv.dovi_metadata);
    assert(!av_opt_set(&s,"dovi_metadata","1",0));
    assert(qsv_decode_init(&avctx)==AVERROR(ENOSYS) && !s.packet_fifo);
    assert(!av_opt_set(&s,"dovi_metadata","0",0));
    assert(!qsv_decode_init(&avctx));
    assert(!qsv_decode_close(&avctx)); av_opt_free(&s);
    puts("QSV Dolby GPL/version3 gate PASS: default OFF, unsupported ON rejected, OFF init/close unchanged");
    return 0;
}
