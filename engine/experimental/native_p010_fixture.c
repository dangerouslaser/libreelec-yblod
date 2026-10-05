/* Private diagnostic packing only: low-aligned native10 planar LE -> P010.
 * No colour conversion, resampling, clipping or rounding. Caller pins SHA256.
 */
#define _POSIX_C_SOURCE 200809L
#ifdef __APPLE__
#define _DARWIN_C_SOURCE
#endif
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int inputs[3] = {-1,-1,-1}, output = -1;
static struct stat initial[3], created;
static const char *destination;
static int own_output;

static void cleanup(void)
{
    for (unsigned i=0; i<3; ++i) if (inputs[i]>=0) close(inputs[i]);
    if (output>=0) close(output);
    if (own_output) {
        struct stat current;
        if (!lstat(destination,&current) && S_ISREG(current.st_mode)
            && current.st_dev==created.st_dev && current.st_ino==created.st_ino)
            unlink(destination);
    }
}
static void fail(const char *message)
{
    fprintf(stderr,"packing rejected: %s\n",message);
    exit(EXIT_FAILURE);
}
static unsigned dimension(const char *text)
{
    unsigned value=0;
    if (!*text) fail("empty dimension");
    for (const unsigned char *s=(const unsigned char *)text; *s; ++s) {
        if (*s<'0' || *s>'9' || value>8192u/10u) fail("invalid dimension");
        value=value*10u+(unsigned)(*s-'0');
        if (value>8192u) fail("dimension bound");
    }
    if (value<2 || value%2) fail("dimensions must be even, 2..8192");
    return value;
}
static int stable(const struct stat *a,const struct stat *b)
{
#ifdef __APPLE__
#define YB_MTIME st_mtimespec
#define YB_CTIME st_ctimespec
#else
#define YB_MTIME st_mtim
#define YB_CTIME st_ctim
#endif
    return a->st_dev==b->st_dev && a->st_ino==b->st_ino
        && a->st_size==b->st_size && a->st_mode==b->st_mode
        && a->YB_MTIME.tv_sec==b->YB_MTIME.tv_sec && a->YB_MTIME.tv_nsec==b->YB_MTIME.tv_nsec
        && a->YB_CTIME.tv_sec==b->YB_CTIME.tv_sec && a->YB_CTIME.tv_nsec==b->YB_CTIME.tv_nsec;
}
static void read_exact(int fd,unsigned char *buffer,size_t bytes)
{
    size_t at=0;
    while (at<bytes) {
        ssize_t got=read(fd,buffer+at,bytes-at);
        if (got<0 && errno==EINTR) continue;
        if (got<=0) fail("source read");
        at+=(size_t)got;
    }
}
static void write_exact(const unsigned char *buffer,size_t bytes)
{
    size_t at=0;
    while (at<bytes) {
        ssize_t count=write(output,buffer+at,bytes-at);
        if (count<0 && errno==EINTR) continue;
        if (count<=0) fail("output write");
        at+=(size_t)count;
    }
}
static void pack_word(unsigned char *out,const unsigned char *in)
{
    unsigned code=(unsigned)in[0]+((unsigned)in[1]<<8);
    if (code>1023) fail("source code is outside native10");
    unsigned word=code<<6;
    out[0]=(unsigned char)(word&255u);
    out[1]=(unsigned char)(word>>8);
}
int main(int argc,char **argv)
{
    if (argc!=7) {
        fprintf(stderr,"usage: native_p010_fixture Y Cb Cr NEW_OUTPUT WIDTH HEIGHT\n");
        return EXIT_FAILURE;
    }
    atexit(cleanup);
    unsigned width=dimension(argv[5]),height=dimension(argv[6]);
    uint64_t sizes[3]={(uint64_t)width*height*2u,(uint64_t)width*height/2u,(uint64_t)width*height/2u};
    for (unsigned i=0;i<3;++i) {
        inputs[i]=open(argv[i+1],O_RDONLY|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK);
        if (inputs[i]<0 || fstat(inputs[i],&initial[i]) || !S_ISREG(initial[i].st_mode)
            || initial[i].st_size<0 || (uint64_t)initial[i].st_size!=sizes[i])
            fail("source must be an exact regular plane");
        for (unsigned j=0;j<i;++j)
            if (initial[i].st_dev==initial[j].st_dev && initial[i].st_ino==initial[j].st_ino)
                fail("source planes alias");
    }
    /* Caller must use a private parent directory. O_EXCL refuses any old path. */
    destination=argv[4];
    output=open(destination,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);
    if (output<0) fail("output must be a new private path");
    if (fstat(output,&created) || !S_ISREG(created.st_mode)) fail("output stat");
    own_output=1;
    unsigned char y[16384], cb[8192],cr[8192],packed[16384];
    for (unsigned row=0;row<height;++row) {
        read_exact(inputs[0],y,(size_t)width*2u);
        for (unsigned x=0;x<width;++x) pack_word(packed+(size_t)x*2u,y+(size_t)x*2u);
        write_exact(packed,(size_t)width*2u);
    }
    for (unsigned row=0;row<height/2u;++row) {
        read_exact(inputs[1],cb,width); read_exact(inputs[2],cr,width);
        for (unsigned x=0;x<width/2u;++x) {
            pack_word(packed+(size_t)x*4u,cb+(size_t)x*2u);
            pack_word(packed+(size_t)x*4u+2u,cr+(size_t)x*2u);
        }
        write_exact(packed,(size_t)width*2u);
    }
    for (unsigned i=0;i<3;++i) {
        unsigned char byte; ssize_t got;
        do {got=read(inputs[i],&byte,1);} while(got<0 && errno==EINTR);
        struct stat final;
        if (got!=0 || fstat(inputs[i],&final) || !stable(&initial[i],&final))
            fail("source changed during packing");
    }
    struct stat final;
    if (fsync(output) || fstat(output,&final) || final.st_size<0
        || (uint64_t)final.st_size!=(uint64_t)width*height*3u) fail("output extent");
    if (close(output)) {output=-1; fail("output close");}
    output=-1;
    own_output=0;
    printf("{\"schema\":\"yblod.native-p010-fixture.v1\",\"status\":\"complete\",\"width\":%u,\"height\":%u,\"output_bytes\":%llu,\"code_shift\":6,\"clipping\":false,\"source_stat_stable\":true}\n",
           width,height,(unsigned long long)((uint64_t)width*height*3u));
    return EXIT_SUCCESS;
}
