/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "native_qsv_bl_duration.h"
#include <assert.h>
#include <stdio.h>
#include <limits.h>
int main(void)
{
    int64_t out = -7;
    assert(yb_duration_microseconds(0,(AVRational){1,1000},&out) && out==0);
    assert(yb_duration_microseconds(41,(AVRational){1,1000},&out) && out==41000);
    assert(yb_duration_microseconds(1,(AVRational){1001,24000},&out) && out==41708);
    assert(yb_duration_microseconds(1,(AVRational){1,2000000},&out) && out==1);
    assert(yb_duration_microseconds(INT64_MAX,(AVRational){1,1000000},&out) && out==INT64_MAX);
    out=-7;
    assert(!yb_duration_microseconds(-1,(AVRational){1,1000},&out) && out==-7);
    assert(!yb_duration_microseconds(INT64_MAX,(AVRational){1,1000},&out) && out==-7);
    assert(!yb_duration_microseconds(INT64_MAX,(AVRational){INT_MAX,1},&out) && out==-7);
    assert(!yb_duration_microseconds(1,(AVRational){0,1000},&out) && out==-7);
    assert(!yb_duration_microseconds(1,(AVRational){1,0},&out) && out==-7);
    assert(!yb_duration_microseconds(1,(AVRational){-1,1000},&out) && out==-7);
    assert(!yb_duration_microseconds(1,(AVRational){1,-1000},&out) && out==-7);
    assert(!yb_duration_microseconds(1,(AVRational){1,INT_MAX},&out) && out==-7);
    assert(!yb_duration_microseconds(1,(AVRational){1,1000},NULL));
    puts("duration_contract_cases=14 all_passed=true hardware_qualified=false");
    return 0;
}



