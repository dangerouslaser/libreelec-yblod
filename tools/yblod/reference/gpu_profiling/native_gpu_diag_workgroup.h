#ifndef YB_NATIVE_GPU_DIAG_WORKGROUP_H
#define YB_NATIVE_GPU_DIAG_WORKGROUP_H
#include <stdint.h>
/* Private diagnostic whitelist, not a production scheduling policy. */
static inline int yb_diag_workgroup_allowed(int x,int y,int z,int sx,int sy,int sz,int invocations)
{
 return ((x==8&&y==8)||(x==16&&y==8)||(x==16&&y==16))&&z==1&&
        x<=sx&&y<=sy&&z<=sz&&invocations>=x*y;
}
static inline uint32_t yb_diag_group_count(uint32_t pixels,uint32_t group)
{return pixels/group+(uint32_t)(pixels%group!=0);}
#endif
