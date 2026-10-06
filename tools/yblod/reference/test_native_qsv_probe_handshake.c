/* CPU-only private live-handoff filesystem/protocol contracts. */
#include "native_qsv_probe_handshake.h"
#include <assert.h>
#include <sys/wait.h>
static const char token[]="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
int main(void)
{
    unsetenv("YB_QSV_PROBE_READY");unsetenv("YB_QSV_PROBE_ACK");unsetenv("YB_QSV_PROBE_NONCE");
    assert(qsv_probe_handshake(0));
    assert(!setenv("YB_QSV_PROBE_NONCE",token,1)&&!qsv_probe_handshake(0));
    for(int mode=0;mode<8;mode++){
        char dir[]="/tmp/yblod-qsv-ready-XXXXXX",ready[256],ack[256],temporary[256];
        assert(mkdtemp(dir));snprintf(ready,sizeof(ready),"%s/ready",dir);snprintf(ack,sizeof(ack),"%s/ack",dir);snprintf(temporary,sizeof(temporary),"%s/ack.tmp",dir);
        assert(!setenv("YB_QSV_PROBE_READY",ready,1)&&!setenv("YB_QSV_PROBE_ACK",ack,1));
        assert(!setenv("YB_QSV_PROBE_NONCE",token,1));
        struct timespec now;assert(!clock_gettime(CLOCK_MONOTONIC,&now));
        if(mode==0){int fd=open(ready,O_CREAT|O_EXCL|O_WRONLY,0600);assert(fd>=0);close(fd);assert(!qsv_probe_handshake(now.tv_sec+2));}
        else if(mode==1){assert(!symlink("/dev/null",ready));assert(!qsv_probe_handshake(now.tv_sec+2));}
        else if(mode==2){assert(!qsv_probe_handshake(now.tv_sec));}
        else if(mode==7){int fd=open(ack,O_CREAT|O_EXCL|O_WRONLY,0600);assert(fd>=0);close(fd);assert(!qsv_probe_handshake(now.tv_sec+2));}
        else{
            pid_t pid=fork();assert(pid>=0);
            if(!pid){
                for(int i=0;i<100;i++){struct stat st;if(!stat(ready,&st)&&st.st_size>0)break;struct timespec wait={.tv_nsec=10000000};nanosleep(&wait,NULL);}
                char text[192];int fd=open(ready,O_RDONLY);assert(fd>=0);ssize_t n=read(fd,text,sizeof(text)-1);assert(n>0);text[n]=0;close(fd);
                assert(strstr(text,token)&&strstr(text,"\"pid\":"));
                fd=open(temporary,O_CREAT|O_EXCL|O_WRONLY,0600);assert(fd>=0);
                assert(write(fd,token,64)==64);
                if(mode==4)assert(write(fd,"\n",1)==1);
                if(mode==5)assert(!fchmod(fd,0644));
                if(mode==6)assert(pwrite(fd,"b",1,0)==1);
                close(fd);assert(!rename(temporary,ack));_exit(0);
            }
            assert(qsv_probe_handshake(now.tv_sec+3)==(mode==3));
            int status;assert(waitpid(pid,&status,0)==pid&&WIFEXITED(status)&&WEXITSTATUS(status)==0);
        }
        unlink(ready);unlink(ack);assert(!rmdir(dir));
    }
    puts("CPU-only optional-env/nonce/fresh-file/symlink/deadline/ack-size-permission contracts PASS");return 0;
}
