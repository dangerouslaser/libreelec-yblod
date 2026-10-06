/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Synthetic literal normalization guard only; not an actual FFmpeg BSF test. */
#include <assert.h>
#include <stdio.h>
#include "native_qsv_bl_payload_guard.h"
int main(void)
{
 uint8_t h[31]={0};h[0]=1;h[21]=3;h[22]=1;h[23]=32;h[25]=1;h[27]=3;h[28]=64;h[29]=1;h[30]=170;
 const uint8_t prefix[]={0,0,0,1,64,1,170};
 const uint8_t original[]={0,0,0,3,2,1,128};
 const uint8_t normalized[]={0,0,0,1,2,1,128};
 uint8_t injected[21];memcpy(injected,prefix,7);memcpy(injected+7,normalized,7);
 struct yb_normalization n={0};assert(yb_normalization_init(&n,h,sizeof(h),prefix,sizeof(prefix)));
 assert(yb_literal_normalized(&n,original,sizeof(original),normalized,sizeof(normalized)));
 assert(yb_literal_normalized(&n,original,sizeof(original),injected,14));
 injected[13]^=1;assert(!yb_literal_normalized(&n,original,sizeof(original),injected,14));injected[13]^=1;
 injected[6]^=1;assert(!yb_literal_normalized(&n,original,sizeof(original),injected,14));injected[6]^=1;
 memcpy(injected+14,normalized,7);assert(!yb_literal_normalized(&n,original,sizeof(original),injected,21));
 memcpy(injected,normalized,7);memcpy(injected+7,prefix,7);assert(!yb_literal_normalized(&n,original,sizeof(original),injected,14));
 assert(!yb_literal_normalized(&n,original,sizeof(original)-1,normalized,sizeof(normalized)));
 yb_normalization_clear(&n);
 h[23]=39;assert(!yb_normalization_init(&n,h,sizeof(h),prefix,sizeof(prefix)));h[23]=32;
 assert(!yb_normalization_init(&n,h,sizeof(h)-1,prefix,sizeof(prefix)));
 assert(!yb_normalization_init(&n,h,sizeof(h),normalized,sizeof(normalized)));
 assert(yb_normalization_init(&n,NULL,0,NULL,0));
 assert(yb_literal_normalized(&n,normalized,sizeof(normalized),normalized,sizeof(normalized)));
 assert(!yb_literal_normalized(&n,original,sizeof(original),normalized,sizeof(normalized)));
 yb_normalization_clear(&n);
 puts("Synthetic exact hvcC-parameter-prefix/literal NAL payload guard contracts PASS");return 0;
}
