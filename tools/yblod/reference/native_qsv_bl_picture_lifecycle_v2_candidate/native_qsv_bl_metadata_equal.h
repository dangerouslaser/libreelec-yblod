/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Diagnostic comparator: public fields only, never struct padding/pointers.
 * Unknown extension levels fail closed. Original RPU trailer bytes stay private.
 * Inactive coefficient slots and full trailer capacity are compared strictly:
 * independently allocated decoder exports are expected to zero-initialize them.
 * A mismatch is a failure, never permission to waive an active-field check. */
#ifndef YB_BL_METADATA_EQUAL_H
#define YB_BL_METADATA_EQUAL_H
#include <libavutil/dovi_meta.h>
#include <libavutil/frame.h>
#define EQ(f) do { if (a->f != b->f) return 0; } while (0)
static int yb_qequal(AVRational a, AVRational b) { return a.num==b.num && a.den==b.den; }
static int yb_xy_equal(AVCIExy a, AVCIExy b) { return yb_qequal(a.x,b.x)&&yb_qequal(a.y,b.y); }
static int yb_prim_equal(AVColorPrimariesDesc a, AVColorPrimariesDesc b)
{ return yb_xy_equal(a.wp,b.wp)&&yb_xy_equal(a.prim.r,b.prim.r)&&yb_xy_equal(a.prim.g,b.prim.g)&&yb_xy_equal(a.prim.b,b.prim.b); }
static int yb_header_equal(const AVDOVIRpuDataHeader *a,const AVDOVIRpuDataHeader *b)
{
 EQ(rpu_type);EQ(rpu_format);EQ(vdr_rpu_profile);EQ(vdr_rpu_level);
 EQ(chroma_resampling_explicit_filter_flag);EQ(coef_data_type);EQ(coef_log2_denom);
 EQ(vdr_rpu_normalized_idc);EQ(bl_video_full_range_flag);EQ(bl_bit_depth);
 EQ(el_bit_depth);EQ(vdr_bit_depth);EQ(spatial_resampling_filter_flag);
 EQ(el_spatial_resampling_filter_flag);EQ(disable_residual_flag);
 EQ(ext_mapping_idc_0_4);EQ(ext_mapping_idc_5_7);return 1;
}
static int yb_mapping_equal(const AVDOVIDataMapping *a,const AVDOVIDataMapping *b)
{
 EQ(vdr_rpu_id);EQ(mapping_color_space);EQ(mapping_chroma_format_idc);
 EQ(nlq_method_idc);EQ(num_x_partitions);EQ(num_y_partitions);
 for(unsigned c=0;c<3;c++) {
  EQ(curves[c].num_pivots);
  if(a->curves[c].num_pivots<2||a->curves[c].num_pivots>9)return 0;
  for(unsigned i=0;i<9;i++)EQ(curves[c].pivots[i]);
  for(unsigned i=0;i<8;i++) {
   EQ(curves[c].mapping_idc[i]);EQ(curves[c].poly_order[i]);
   EQ(curves[c].mmr_order[i]);EQ(curves[c].mmr_constant[i]);
   for(unsigned j=0;j<3;j++) {
    EQ(curves[c].poly_coef[i][j]);
    for(unsigned k=0;k<7;k++)EQ(curves[c].mmr_coef[i][j][k]);
   }
  }
  EQ(nlq[c].nlq_offset);EQ(nlq[c].vdr_in_max);
  EQ(nlq[c].linear_deadzone_slope);EQ(nlq[c].linear_deadzone_threshold);
 }
 for(unsigned i=0;i<2;i++){EQ(nlq_pivots[i]);}return 1;
}
static int yb_color_equal(const AVDOVIColorMetadata *a,const AVDOVIColorMetadata *b)
{
 EQ(dm_metadata_id);EQ(scene_refresh_flag);
 for(unsigned i=0;i<9;i++)if(!yb_qequal(a->ycc_to_rgb_matrix[i],b->ycc_to_rgb_matrix[i])||!yb_qequal(a->rgb_to_lms_matrix[i],b->rgb_to_lms_matrix[i]))return 0;
 for(unsigned i=0;i<3;i++)if(!yb_qequal(a->ycc_to_rgb_offset[i],b->ycc_to_rgb_offset[i]))return 0;
 EQ(signal_eotf);EQ(signal_eotf_param0);EQ(signal_eotf_param1);EQ(signal_eotf_param2);
 EQ(signal_bit_depth);EQ(signal_color_space);EQ(signal_chroma_format);EQ(signal_full_range_flag);
 EQ(source_min_pq);EQ(source_max_pq);EQ(source_diagonal);return 1;
}
static int yb_ext_equal(const AVDOVIDmData *a,const AVDOVIDmData *b)
{
 EQ(level);
 switch(a->level) {
 case 1:EQ(l1.min_pq);EQ(l1.max_pq);EQ(l1.avg_pq);break;
 case 2:EQ(l2.target_max_pq);EQ(l2.trim_slope);EQ(l2.trim_offset);EQ(l2.trim_power);EQ(l2.trim_chroma_weight);EQ(l2.trim_saturation_gain);EQ(l2.ms_weight);break;
 case 3:EQ(l3.min_pq_offset);EQ(l3.max_pq_offset);EQ(l3.avg_pq_offset);break;
 case 4:EQ(l4.anchor_pq);EQ(l4.anchor_power);break;
 case 5:EQ(l5.left_offset);EQ(l5.right_offset);EQ(l5.top_offset);EQ(l5.bottom_offset);break;
 case 6:EQ(l6.max_luminance);EQ(l6.min_luminance);EQ(l6.max_cll);EQ(l6.max_fall);break;
 case 8:EQ(l8.target_display_index);EQ(l8.trim_slope);EQ(l8.trim_offset);EQ(l8.trim_power);EQ(l8.trim_chroma_weight);EQ(l8.trim_saturation_gain);EQ(l8.ms_weight);EQ(l8.target_mid_contrast);EQ(l8.clip_trim);for(unsigned i=0;i<6;i++){EQ(l8.saturation_vector_field[i]);EQ(l8.hue_vector_field[i]);}break;
 case 9:EQ(l9.source_primary_index);if(!yb_prim_equal(a->l9.source_display_primaries,b->l9.source_display_primaries))return 0;break;
 case 10:EQ(l10.target_display_index);EQ(l10.target_max_pq);EQ(l10.target_min_pq);EQ(l10.target_primary_index);if(!yb_prim_equal(a->l10.target_display_primaries,b->l10.target_display_primaries))return 0;break;
 case 11:EQ(l11.content_type);EQ(l11.whitepoint);EQ(l11.reference_mode_flag);
#if FF_API_DOVI_L11_INVALID_PROPS
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wdeprecated-declarations"
 /* The diagnostic intentionally inventories legacy fields still in this ABI. */
 EQ(l11.sharpness);EQ(l11.noise_reduction);EQ(l11.mpeg_noise_reduction);EQ(l11.frame_rate_conversion);EQ(l11.brightness);EQ(l11.color);
#pragma GCC diagnostic pop
#endif
 break;
 case 254:EQ(l254.dm_mode);EQ(l254.dm_version_index);break;
 case 255:EQ(l255.dm_run_mode);EQ(l255.dm_run_version);for(unsigned i=0;i<4;i++)EQ(l255.dm_debug[i]);break;
 default:return 0;
 }
 EQ(dvbridge_raw_magic);EQ(dvbridge_original_length);
 if(a->dvbridge_original_length>sizeof(a->dvbridge_original_bytes))return 0;
 for(unsigned i=0;i<sizeof(a->dvbridge_original_bytes);i++)EQ(dvbridge_original_bytes[i]);
 return 1;
}
static int yb_span(size_t offset,size_t length,size_t size)
{return offset>=sizeof(AVDOVIMetadata)&&offset<=size&&length<=size-offset;}
static int yb_typed_span(const void *base,size_t offset,size_t length,size_t size,size_t alignment)
{return yb_span(offset,length,size)&&((uintptr_t)base%alignment+offset%alignment)%alignment==0;}
static int yb_metadata_valid(const AVFrameSideData *s)
{
 if(!s||!s->data||s->size<sizeof(AVDOVIMetadata)||(uintptr_t)s->data%_Alignof(AVDOVIMetadata))return 0;
 const AVDOVIMetadata *m=(const void*)s->data;
 if(!yb_typed_span(s->data,m->header_offset,sizeof(AVDOVIRpuDataHeader),s->size,_Alignof(AVDOVIRpuDataHeader))||!yb_typed_span(s->data,m->mapping_offset,sizeof(AVDOVIDataMapping),s->size,_Alignof(AVDOVIDataMapping))||!yb_typed_span(s->data,m->color_offset,sizeof(AVDOVIColorMetadata),s->size,_Alignof(AVDOVIColorMetadata))||m->num_ext_blocks<0||m->num_ext_blocks>AV_DOVI_MAX_EXT_BLOCKS)return 0;
 if(m->mapping_offset<m->header_offset+sizeof(AVDOVIRpuDataHeader)||m->color_offset<m->mapping_offset+sizeof(AVDOVIDataMapping))return 0;
 if(!m->num_ext_blocks)return 1;
 return m->ext_block_offset>=m->color_offset+sizeof(AVDOVIColorMetadata)&&m->ext_block_size>=sizeof(AVDOVIDmData)&&m->ext_block_size%_Alignof(AVDOVIDmData)==0&&m->ext_block_size<=s->size/(size_t)m->num_ext_blocks&&yb_typed_span(s->data,m->ext_block_offset,m->ext_block_size*(size_t)m->num_ext_blocks,s->size,_Alignof(AVDOVIDmData));
}
static int yb_metadata_equal(const AVFrame *reference,const AVFrame *candidate)
{
 AVFrameSideData *sa=av_frame_get_side_data(reference,AV_FRAME_DATA_DOVI_METADATA),*sb=av_frame_get_side_data(candidate,AV_FRAME_DATA_DOVI_METADATA);
 if(!yb_metadata_valid(sa)||!yb_metadata_valid(sb))return 0;
 const AVDOVIMetadata *a=(const void*)sa->data,*b=(const void*)sb->data;
 EQ(num_ext_blocks);
 if(!yb_header_equal(av_dovi_get_header(a),av_dovi_get_header(b))||!yb_mapping_equal(av_dovi_get_mapping(a),av_dovi_get_mapping(b))||!yb_color_equal(av_dovi_get_color(a),av_dovi_get_color(b)))return 0;
 for(int i=0;i<a->num_ext_blocks;i++)if(!yb_ext_equal(av_dovi_get_ext(a,i),av_dovi_get_ext(b,i)))return 0;
 return 1;
}
#undef EQ
#endif
