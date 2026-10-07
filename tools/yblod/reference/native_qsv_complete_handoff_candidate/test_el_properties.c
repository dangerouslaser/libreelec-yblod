#include "dvbridge_fel_qsv_tokens.h"
#undef NDEBUG
#include <assert.h>
#include <stdio.h>

int main(void)
{
    struct dvbridge_qsv_tokens map={0};
    struct dvbridge_qsv_properties expected[32];
    int64_t token, again;
    for (int i=0;i<32;i++) {
        expected[i]=(struct dvbridge_qsv_properties){1920,1080,10,3,2,9,16,9,i+1,33};
        assert(dvbridge_qsv_token_peek(&map,100+i,&token));
        assert(dvbridge_qsv_token_peek(&map,100+i,&again) && token==again);
        struct dvbridge_qsv_properties properties=expected[i];
        assert(dvbridge_qsv_token_commit_properties(&map,token,100+i,41,&properties));
        properties.width=1; /* committed metadata must not alias this input */
        assert(!dvbridge_qsv_token_peek(&map,100+i,&again));
    }
    for (int i=31;i>=0;i--) {
        struct dvbridge_qsv_timestamp out;
        assert(dvbridge_qsv_token_take(&map,i+1,&out));
        assert(out.pts==100+i && out.duration==41 && out.properties_valid);
        assert(!memcmp(&out.properties,&expected[i],sizeof(out.properties)));
    }
    assert(map.count==0);
    assert(dvbridge_qsv_token_peek(&map,1000,&token));
    struct dvbridge_qsv_properties bad={0};
    assert(!dvbridge_qsv_token_commit_properties(&map,token,1000,41,&bad));
    assert(map.count==0);
    assert(dvbridge_qsv_token_commit_properties(&map,token,1000,41,&expected[0]));
    dvbridge_qsv_tokens_reset(&map);
    struct dvbridge_qsv_timestamp out;
    assert(!dvbridge_qsv_token_take(&map,token,&out));
    assert(dvbridge_qsv_token_peek(&map,1001,&again) && again>token);
    puts("PASS: 32 EL property snapshots, reverse output, EAGAIN peek, duplicates, invalid properties, stale seek token");
    return 0;
}
