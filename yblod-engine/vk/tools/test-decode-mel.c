/* Live helper probe: per-frame BL metadata and layer ownership across reopen.
 * Usage: test-decode-mel MOVIE METADATA_DUMP EXPECT_EL(0|1). */
#include "decode.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
int main(int argc,char **argv) {
    assert(argc==4);int expected=atoi(argv[3]);FILE *out=fopen(argv[2],"wb");assert(out);
    for(int session=0;session<2;session++) {
        struct dv_decoder d;assert(!dv_decoder_open(&d,argv[1],"/dev/dri/renderD128",120));
        int el=0,metadata=0;
        for(int n=0;n<64;n++) {
            struct dv_pair p;assert(dv_decoder_next(&d,&p)==1);
            assert((p.el!=NULL)==expected);el+=p.el!=NULL;
            const AVFrameSideData *bl=av_frame_get_side_data(p.bl,AV_FRAME_DATA_DOVI_METADATA);
            assert(bl && p.dovi==bl);metadata++;
            assert(fwrite(&bl->size,sizeof(bl->size),1,out)==1);
            assert(fwrite(bl->data,1,bl->size,out)==bl->size);
            dv_pair_free(&p);
        }
        dv_decoder_close(&d);
        printf("session=%d frames=64 el=%d BL_metadata=%d PASS\n",session,el,metadata);
    }
    assert(!fclose(out));
}
