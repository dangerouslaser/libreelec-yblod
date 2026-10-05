#ifndef YB_NATIVE_TEXTURE_FIXTURE_H
#define YB_NATIVE_TEXTURE_FIXTURE_H
#include <stdint.h>
#include <string.h>
#define YB_TEXTURE_WIDTH 8
#define YB_TEXTURE_HEIGHT 2
#define YB_TEXTURE_QUERIES 112
#define YB_TEXTURE_WORDS 36

/* Fixed public synthetic data only. Coordinates are logical texel centres /4. */
struct yb_texture_fixture {
    uint16_t pixels[8*2*4];
    int32_t queries[YB_TEXTURE_QUERIES*4];
    uint32_t parameters[5]; /* count, scale, offset, slope, threshold float bits */
};
static uint32_t yb_float_bits(float value)
{ uint32_t bits; memcpy(&bits,&value,sizeof(bits)); return bits; }
static void yb_texture_query(struct yb_texture_fixture *f,unsigned *count,int x,int y)
{
    int ix=x>=0?x/4:-((-x+3)/4),iy=y>=0?y/4:-((-y+3)/4);
    if(ix<0)ix=0;
    if(ix>7)ix=7;
    if(iy<0)iy=0;
    if(iy>1)iy=1;
    for(int mode=0;mode<2;++mode) {
        unsigned k=(*count)++;
        f->queries[4*k]=x; f->queries[4*k+1]=y;
        f->queries[4*k+2]=mode; f->queries[4*k+3]=iy*8+ix;
    }
}
static void yb_texture_fixture_init(struct yb_texture_fixture *f)
{
    const uint16_t words[8]={0,32704,32752,32767,32768,32769,32784,65535};
    memset(f,0,sizeof(*f));
    for(unsigned y=0;y<2;++y)for(unsigned x=0;x<8;++x) {
        unsigned k=4*(y*8+x);
        f->pixels[k]=words[(x+2*y)%8];
        f->pixels[k+1]=y? (uint16_t)(65535U-words[x]):words[x];
        f->pixels[k+2]=words[7-x];
        f->pixels[k+3]=(uint16_t)((x+y)%2?65535:0);
    }
    /* Explicit integer upper neighbour omitted by the first pattern. */
    f->pixels[4*8+1]=32832;
    unsigned count=0;
    for(int y=0;y<2;++y)for(int x=0;x<8;++x)yb_texture_query(f,&count,4*x,4*y);
    for(int y=0;y<2;++y)for(int x=0;x<8;++x)yb_texture_query(f,&count,4*x+2,4*y);
    for(int x=0;x<8;++x)yb_texture_query(f,&count,4*x+1,0);
    for(int x=0;x<8;++x)yb_texture_query(f,&count,4*x,2);
    const int boundary[8][2]={{-4,0},{-2,0},{32,0},{34,0},{0,-4},{0,-2},{0,8},{0,10}};
    for(unsigned i=0;i<8;++i)yb_texture_query(f,&count,boundary[i][0],boundary[i][1]);
    f->parameters[0]=count;
    float scale=1.0f/64.0f;
    scale=(float)((double)scale*(65535.0/1023.0));
    const float el_scale=1.0f/1023.0f;
    f->parameters[1]=yb_float_bits(scale);
    f->parameters[2]=yb_float_bits(el_scale*512.0f);
    f->parameters[3]=yb_float_bits((float)((1023.0/8388608.0)*2048.0));
    f->parameters[4]=yb_float_bits((float)(-1024.0/8388608.0));
}
#endif
