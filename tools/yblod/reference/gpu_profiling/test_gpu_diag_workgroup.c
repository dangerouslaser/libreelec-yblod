#include "native_gpu_diag_workgroup.h"
#include <assert.h>
#include <stdio.h>
int main(void)
{
 assert(yb_diag_workgroup_allowed(8,8,1,1024,1024,64,64));
 assert(yb_diag_workgroup_allowed(16,8,1,1024,1024,64,128));
 assert(yb_diag_workgroup_allowed(16,16,1,16,16,1,256));
 assert(!yb_diag_workgroup_allowed(8,16,1,1024,1024,64,1024));
 assert(!yb_diag_workgroup_allowed(16,16,2,1024,1024,64,1024));
 assert(!yb_diag_workgroup_allowed(16,16,1,15,16,1,256));
 assert(!yb_diag_workgroup_allowed(16,16,1,16,15,1,256));
 assert(!yb_diag_workgroup_allowed(16,16,1,16,16,0,256));
 assert(!yb_diag_workgroup_allowed(16,16,1,16,16,1,255));
 assert(yb_diag_group_count(3840,8)==480&&yb_diag_group_count(2160,8)==270);
 assert(yb_diag_group_count(3840,16)==240&&yb_diag_group_count(2160,16)==135);
 assert(yb_diag_group_count(18,16)==2&&yb_diag_group_count(2,16)==1);
 assert(yb_diag_group_count(UINT32_MAX,16)==268435456);
 puts("diagnostic workgroup whitelist, hardware limits, ceil dispatch PASS");return 0;
}
