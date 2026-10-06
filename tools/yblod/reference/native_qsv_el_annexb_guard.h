/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Prefix-only normalization guard; never export NAL payloads. */
static int annexb_payload_equal(const AVPacket *original, const AVPacket *converted,
                               int length_size, int present[3])
{
    int in=0,out=0;
    if(length_size<1 || length_size>4 || original->size<=0 || converted->size<=0)
        return 0;
    while(in<original->size){
        if(original->size-in<length_size)return 0;
        unsigned size=0;
        for(int i=0;i<length_size;i++)size=(size<<8)|original->data[in++];
        if(size<2 || size>(unsigned)(original->size-in))return 0;
        int prefix=0;
        if(converted->size-out>=4 && !converted->data[out] && !converted->data[out+1] &&
           !converted->data[out+2] && converted->data[out+3]==1)prefix=4;
        else if(converted->size-out>=3 && !converted->data[out] && !converted->data[out+1] &&
                converted->data[out+2]==1)prefix=3;
        if(!prefix)return 0;
        out+=prefix;
        if(size>(unsigned)(converted->size-out) || memcmp(original->data+in,converted->data+out,size))return 0;
        int type=(original->data[in]>>1)&63;
        if(type>=32 && type<=34)present[type-32]=1;
        in+=size;out+=size;
    }
    return out==converted->size;
}
