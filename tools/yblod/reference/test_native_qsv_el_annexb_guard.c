/* SPDX-License-Identifier: GPL-3.0-or-later */
#include <libavcodec/packet.h>
#include <assert.h>
#include <string.h>
#include <stdio.h>
#include "native_qsv_el_annexb_guard.h"
int main(void)
{
    AVPacket *a=av_packet_alloc(),*b=av_packet_alloc();assert(a&&b);
    assert(!av_new_packet(a,18)&&!av_new_packet(b,18));
    const uint8_t original[]={0,0,0,2,64,1,0,0,0,2,66,1,0,0,0,2,68,1};
    const uint8_t annex[]={0,0,0,1,64,1,0,0,0,1,66,1,0,0,0,1,68,1};
    memcpy(a->data,original,18);memcpy(b->data,annex,18);
    int p[3]={0};assert(annexb_payload_equal(a,b,4,p)&&p[0]&&p[1]&&p[2]);
    b->data[11]=2;assert(!annexb_payload_equal(a,b,4,p));b->data[11]=1;
    a->data[3]=3;assert(!annexb_payload_equal(a,b,4,p));a->data[3]=2;
    b->size=17;assert(!annexb_payload_equal(a,b,4,p));b->size=18;
    assert(!annexb_payload_equal(a,b,0,p)&&!annexb_payload_equal(a,b,5,p));
    av_packet_free(&a);av_packet_free(&b);
    puts("CPU-only exact EL NAL payload/prefix bounds guard PASS");return 0;
}
