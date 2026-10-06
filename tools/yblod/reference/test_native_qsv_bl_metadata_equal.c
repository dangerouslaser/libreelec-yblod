/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Source-only draft. Must be built against the actual patched SDK ABI. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <libavutil/mem.h>
#include "native_qsv_bl_metadata_equal.h"
static AVFrame *fixture(void)
{
 size_t size=0;AVDOVIMetadata *m=av_dovi_metadata_alloc(&size);
 AVFrame *f=av_frame_alloc();assert(m&&f);
 AVFrameSideData *s=av_frame_new_side_data(f,AV_FRAME_DATA_DOVI_METADATA,size);
 assert(s);memcpy(s->data,m,size);av_free(m);
 m=(void*)s->data;
 for(int c=0;c<3;c++)av_dovi_get_mapping(m)->curves[c].num_pivots=2;
 m->num_ext_blocks=1;av_dovi_get_ext(m,0)->level=1;
 assert(yb_metadata_valid(s));return f;
}
int main(void)
{
 AVFrame *a=fixture(),*b=fixture();
 AVFrameSideData *s=av_frame_get_side_data(b,AV_FRAME_DATA_DOVI_METADATA);
 AVDOVIMetadata *m=(void*)s->data;AVDOVIMetadata saved=*m;
 assert(yb_metadata_equal(a,b));
 AVFrameSideData bad=*s;bad.data=NULL;assert(!yb_metadata_valid(&bad));
 bad=*s;bad.size=sizeof(AVDOVIMetadata)-1;assert(!yb_metadata_valid(&bad));
 bad=*s;bad.data=s->data+1;assert(!yb_metadata_valid(&bad));
#define BAD(field,value) do {m->field=(value);assert(!yb_metadata_valid(s));*m=saved;} while(0)
 BAD(header_offset,SIZE_MAX);BAD(mapping_offset,SIZE_MAX);BAD(color_offset,SIZE_MAX);
 BAD(header_offset,saved.header_offset+1);BAD(mapping_offset,saved.mapping_offset+1);
 BAD(color_offset,saved.color_offset+1);BAD(ext_block_offset,saved.ext_block_offset+1);
 BAD(ext_block_size,SIZE_MAX);BAD(ext_block_size,sizeof(AVDOVIDmData)-1);
 BAD(ext_block_size,saved.ext_block_size+1);BAD(num_ext_blocks,-1);
 BAD(num_ext_blocks,AV_DOVI_MAX_EXT_BLOCKS+1);
 BAD(mapping_offset,saved.header_offset);BAD(color_offset,saved.mapping_offset);
 BAD(ext_block_offset,saved.color_offset);
#undef BAD
#define FLIP(pointer,field) do {(pointer)->field^=1;assert(!yb_metadata_equal(a,b));(pointer)->field^=1;assert(yb_metadata_equal(a,b));} while(0)
 FLIP(av_dovi_get_header(m),rpu_format);
 FLIP(av_dovi_get_mapping(m),curves[0].poly_coef[0][0]);
 FLIP(av_dovi_get_mapping(m),curves[1].mmr_coef[0][0][0]);
 FLIP(av_dovi_get_mapping(m),nlq[2].linear_deadzone_threshold);
 FLIP(av_dovi_get_color(m),signal_eotf_param2);
 FLIP(av_dovi_get_color(m),ycc_to_rgb_matrix[0].num);
 FLIP(av_dovi_get_ext(m,0),l1.max_pq);
 FLIP(av_dovi_get_ext(m,0),dvbridge_original_bytes[31]);
#undef FLIP
 AVDOVIDmData *ext=av_dovi_get_ext(m,0);ext->level=7;
 assert(!yb_metadata_equal(a,b));ext->level=1;
 ext->dvbridge_original_length=33;assert(!yb_metadata_equal(a,b));ext->dvbridge_original_length=0;
 av_dovi_get_mapping(m)->curves[0].num_pivots=10;assert(!yb_metadata_equal(a,b));
 av_dovi_get_mapping(m)->curves[0].num_pivots=2;
 assert(yb_metadata_equal(a,b));av_frame_free(&a);av_frame_free(&b);
 puts("CPU metadata bounds/alignment/count/order/family-mutation contracts PASS");return 0;
}
