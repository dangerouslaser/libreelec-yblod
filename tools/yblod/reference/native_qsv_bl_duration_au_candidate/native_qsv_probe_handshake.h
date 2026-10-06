/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Optional diagnostic-only live identity handoff. No production decoder API. */
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>
static int qsv_probe_handshake(time_t global_deadline)
{
    const char *ready=getenv("YB_QSV_PROBE_READY"),*ack=getenv("YB_QSV_PROBE_ACK"),*nonce=getenv("YB_QSV_PROBE_NONCE");
    if(!ready&&!ack&&!nonce)return 1;
    if(!ready||!ack||!nonce||ready[0]!='/'||ack[0]!='/'||!strcmp(ready,ack)||strlen(nonce)!=64)return 0;
    for(int i=0;i<64;i++)if(!((nonce[i]>='0'&&nonce[i]<='9')||(nonce[i]>='a'&&nonce[i]<='f')))return 0;
    struct timespec now;
    if(clock_gettime(CLOCK_MONOTONIC,&now)||now.tv_sec>=global_deadline)return 0;
    time_t limit=now.tv_sec+10;
    if(limit>global_deadline)limit=global_deadline;
    struct stat st;
    if(!lstat(ack,&st))return 0;
    int fd=open(ready,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
    if(fd<0)return 0;
    char record[192];
    int n=snprintf(record,sizeof(record),"{\"pid\":%ld,\"nonce\":\"%s\"}\n",(long)getpid(),nonce);
    int valid=!fstat(fd,&st)&&S_ISREG(st.st_mode)&&(st.st_mode&0777)==0600&&st.st_uid==getuid()&&
        n>0&&(size_t)n<sizeof(record)&&write(fd,record,n)==n;
    close(fd);if(!valid)return 0;
    for(;;){
        if(clock_gettime(CLOCK_MONOTONIC,&now)||now.tv_sec>=limit)return 0;
        if(!lstat(ack,&st)){
            if(!S_ISREG(st.st_mode)||(st.st_mode&0777)!=0600||st.st_uid!=getuid())return 0;
            fd=open(ack,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);if(fd<0)return 0;
            struct stat actual;char value[65];
            ssize_t count=read(fd,value,sizeof(value));
            valid=!fstat(fd,&actual)&&actual.st_dev==st.st_dev&&actual.st_ino==st.st_ino&&
                S_ISREG(actual.st_mode)&&(actual.st_mode&0777)==0600&&actual.st_uid==getuid()&&
                actual.st_size==64&&count==64&&!memcmp(value,nonce,64);
            close(fd);return valid;
        }
        struct timespec pause={.tv_nsec=20000000};nanosleep(&pause,NULL);
    }
}



