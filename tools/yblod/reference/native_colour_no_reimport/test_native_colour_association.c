#include "dvbridge_native_colour.h"
#include <assert.h>
#include <stdio.h>
static struct dvbridge_native_colour_association valid(void)
{
 struct dvbridge_native_colour_association p={0};
 p.version=1;p.width=p.height=64;p.enhancement_width=p.enhancement_height=32;
 p.vaapi_p010_admitted=p.unrotated=1;p.reconstructed_depth=12;
 p.bl_pts=p.el_pts=123;p.timebase_num=1;p.timebase_den=24;
 p.expected_frame_id[0]=p.reconstructed_frame_id[0]=1;
 p.presentation_pts=p.enhancement_presentation_pts=123;
 return p;
}
int main(void)
{
 struct dvbridge_native_colour_association p=valid();assert(dvbridge_native_colour_association_valid(&p));
 assert(!dvbridge_native_colour_association_valid(NULL));
#define REJECT(field,value) do{p=valid();p.field=value;assert(!dvbridge_native_colour_association_valid(&p));}while(0)
 REJECT(version,0);REJECT(width,0);REJECT(height,2162);REJECT(width,65);
 REJECT(enhancement_width,0);REJECT(enhancement_height,2161);
 REJECT(vaapi_p010_admitted,0);REJECT(unrotated,0);REJECT(reconstructed_depth,10);
 REJECT(bl_pts,INT64_MIN);REJECT(el_pts,124);REJECT(timebase_num,0);REJECT(timebase_den,-1);
 REJECT(presentation_pts,NAN);REJECT(enhancement_presentation_pts,INFINITY);
 REJECT(enhancement_presentation_pts,124);
#undef REJECT
 p=valid();p.reconstructed_frame_id[0]=2;assert(!dvbridge_native_colour_association_valid(&p));
 p=valid();memset(p.expected_frame_id,0,32);memset(p.reconstructed_frame_id,0,32);assert(!dvbridge_native_colour_association_valid(&p));
 p=valid();p.presentation_pts=0;p.enhancement_presentation_pts=0.00001;assert(!dvbridge_native_colour_association_valid(&p));
 p=valid();p.width=3840;p.height=2160;p.enhancement_width=1920;p.enhancement_height=1080;
 assert(dvbridge_native_colour_association_valid(&p));
 puts("native colour association: valid native descriptors and invalid admission/frame/PTS/geometry cases PASS");return 0;
}
