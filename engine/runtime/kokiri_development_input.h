/* Typed development commands for verified disposable sessions. No raw commands,
 * addresses, paths or unbounded held inputs cross this interface. Included by input.c. */
#pragma once
#include <math.h>
#include <unistd.h>
extern int runtime_kokiri_development_nonce_matches(const char *) __attribute__((weak_import));
extern int runtime_kokiri_development_active(void) __attribute__((weak_import));
extern void runtime_kokiri_development_user_takeover(void) __attribute__((weak_import));
extern void runtime_front_request_agent_close(void);

static void kokiri_dev_reply(const char *id, const char *status, int64_t polls) {
    const char *path = getenv("OOT_EDITOR_STATUS");
    if (!path) return;
    int fd = open(path, O_WRONLY | O_APPEND | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    struct stat info;
    if (fd < 0) return;
    if (!fstat(fd, &info) && S_ISREG(info.st_mode) && info.st_uid == getuid() && info.st_nlink == 1) {
        char line[200]; int n = snprintf(line, sizeof line,
            "{\"id\":\"%s\",\"status\":\"%s\",\"guest_polls\":%lld}\n", id, status, (long long)polls);
        if (n > 0 && (size_t)n < sizeof line) (void)!write(fd, line, (size_t)n);
    }
    close(fd);
}
static int kokiri_dev_key(const char *name) {
    static const struct { const char *name; int key; } keys[] = {
        {"a",38},{"b",40},{"x",34},{"y",32},{"l",12},{"r",14},
        {"zl",58},{"zr",56},{"plus",36},{"minus",48},{"l3",6},{"r3",8},
        {"left",3},{"up",17},{"right",4},{"down",5}};
    for (unsigned i=0;i<sizeof keys/sizeof *keys;i++) if (!strcmp(keys[i].name,name)) return keys[i].key;
    return -1;
}
static int64_t kokiri_dev_poll_count(void) {
    pthread_mutex_lock(&inputLock); int64_t value=kokiriDevDelivered; pthread_mutex_unlock(&inputLock); return value;
}
static int kokiri_dev_hold(const char *nonce, unsigned ms) {
    for (unsigned elapsed=0;elapsed<ms;) {
        if (!runtime_kokiri_development_nonce_matches(nonce)) return 0;
        unsigned slice=ms-elapsed; if(slice>20)slice=20;
        usleep(slice*1000); elapsed+=slice;
    }
    return runtime_kokiri_development_nonce_matches(nonce);
}
static int kokiri_dev_command(const char *line) {
    if(strncmp(line,"kokiri-dev ",11))return 0;
    char nonce[65]={0},id[40]={0},op[24]={0};int used=0;
    if(sscanf(line,"kokiri-dev %64s %39s %23s %n",nonce,id,op,&used)!=3||!used)return 1;
    for(unsigned i=0;id[i];i++)if(!((id[i]>='a'&&id[i]<='z')||(id[i]>='0'&&id[i]<='9')||id[i]=='-'))return 1;
    if(!runtime_kokiri_development_nonce_matches||!runtime_kokiri_development_nonce_matches(nonce)){
        kokiri_dev_reply(id,"lease-refused",0);return 1;
    }
    char text[1200];snprintf(text,sizeof text,"%s",line+used);text[strcspn(text,"\r\n")]=0;
    size_t length=strlen(text);while(length&&text[length-1]==' ')text[--length]=0;
    unsigned ms=0;int end=0;char name[32]={0};
    if(!strcmp(op,"button")&&sscanf(text,"%31s %u %n",name,&ms,&end)==2&&end&&!text[end]&&ms>=1&&ms<=5000){
        int key=kokiri_dev_key(name);if(key<0){kokiri_dev_reply(id,"invalid",0);return 1;}
        int64_t before=kokiri_dev_poll_count();
        pthread_mutex_lock(&inputLock);kokiriDevButtons=button((unsigned)key);atomic_store(&kokiriDevInputActive,1);pthread_mutex_unlock(&inputLock);
        int okay=kokiri_dev_hold(nonce,ms);
        pthread_mutex_lock(&inputLock);atomic_store(&kokiriDevInputActive,0);kokiriDevButtons=0;int64_t delivered=kokiriDevDelivered-before;pthread_mutex_unlock(&inputLock);
        kokiri_dev_reply(id,!okay?"lease-refused":delivered?"completed":"undelivered",delivered);
    } else if(!strcmp(op,"stick")) {
        float x=0,y=0;end=0;
        if(sscanf(text,"%31s %f %f %u %n",name,&x,&y,&ms,&end)!=4||!end||text[end]||
           !isfinite(x)||!isfinite(y)||fabsf(x)>1||fabsf(y)>1||ms<1||ms>5000||
           (strcmp(name,"left")&&strcmp(name,"right"))){kokiri_dev_reply(id,"invalid",0);return 1;}
        int axis=!strcmp(name,"right")?2:0;int64_t before=kokiri_dev_poll_count();
        pthread_mutex_lock(&inputLock);atomic_store(&kokiriDevInputActive,1);kokiriDevAxes[axis]=(int32_t)(x*32767);kokiriDevAxes[axis+1]=(int32_t)(y*32767);pthread_mutex_unlock(&inputLock);
        int okay=kokiri_dev_hold(nonce,ms);
        pthread_mutex_lock(&inputLock);atomic_store(&kokiriDevInputActive,0);int64_t delivered=kokiriDevDelivered-before;memset(kokiriDevAxes,0,sizeof kokiriDevAxes);pthread_mutex_unlock(&inputLock);
        kokiri_dev_reply(id,!okay?"lease-refused":delivered?"completed":"undelivered",delivered);
    } else if(!strcmp(op,"move")||!strcmp(op,"warp")||!strcmp(op,"position")) {
#if defined(GAME_OOT) && !TARGET_OS_IPHONE
        char command[1200];int n=snprintf(command,sizeof command,"oot-live %s %s %s\n",id,op,text);
        if(n>0&&(size_t)n<sizeof command)runtime_oot_live_command(command);
        else kokiri_dev_reply(id,"invalid",0);
#else
        kokiri_dev_reply(id,"unsupported",0);
#endif
    } else if(!strcmp(op,"settings")&&sscanf(text,"%d %n",&end,&used)==1&&used&&!text[used]&&end>=-1&&end<=4){
        runtime_settings_page(end);kokiri_dev_reply(id,"acknowledged",0);
    } else if(!strcmp(op,"close")&&!text[0]){
        kokiri_dev_reply(id,"close-requested",0);runtime_front_request_agent_close();
    } else kokiri_dev_reply(id,"invalid",0);
    return 1;
}
