#ifndef VILLAGE_SOCIAL_SYNC_INC
#define VILLAGE_SOCIAL_SYNC_INC

/* Original game endpoint capture v2_face_EF_chat_otherplayer:
   CB22 12B and CB23 108B are C2S requests followed by one S2C actor broadcast.
   Build a fresh, zeroed response; never echo the client's uninitialized padding. */
#ifndef VILLAGE_SOCIAL_LOCAL_UID
#define VILLAGE_SOCIAL_LOCAL_UID 1u
#endif

static unsigned village_social_u16(const unsigned char *p,int off){return (unsigned)p[off]|((unsigned)p[off+1]<<8);}
static void village_social_put16(char *p,int off,unsigned v){p[off]=(char)(v&0xFFu);p[off+1]=(char)((v>>8)&0xFFu);}

/* A fixed field is valid only when a NUL occurs inside cap bytes and all bytes
   before it form GBK: ASCII 01..7F or lead 81..FE + trail 40..FE except 7F. */
static int village_social_gbk_zlen(const unsigned char *s,unsigned cap,unsigned *out_len){
    unsigned i=0;
    while(i<cap && s[i]){
        unsigned a=s[i];
        if(a<=0x7Fu){i++;continue;}
        if(a<0x81u || a>0xFEu || i+1u>=cap || s[i+1u]==0u)return 0;
        {unsigned b=s[i+1u];if(b<0x40u || b>0xFEu || b==0x7Fu)return 0;}
        i+=2u;
    }
    if(i>=cap)return 0;
    if(out_len)*out_len=i;
    return 1;
}

static int village_social_valid_emotion(unsigned code,unsigned category){
    if(category==8u)return code>=1u && code<=8u;   /* face-expression selector */
    if(category==0u)return code<=30u;              /* ordinary/floating emoticon selector */
    return 0;
}

static void village_social_send_cb22(SOCKET c,unsigned uid,unsigned code,unsigned category){
    char p[4096];mkpkt(p,0xCB22,12,1);
    village_social_put16(p,8,uid);p[0x0A]=(char)code;p[0x0B]=(char)category;
    sendbuf(c,p,12);
    printf("  S0xCB22 social actor-broadcast uid=%u code=%u category=%u len=12\n",uid,code,category);fflush(0);
}

static void village_social_send_cb23_all(SOCKET c,unsigned uid,const unsigned char *text,unsigned text_len){
    char p[4096];mkpkt(p,0xCB23,108,1);
    village_social_put16(p,8,uid);village_social_put16(p,0x0A,1000u);
    stable_name(p+0x0C);                    /* coherent configured GBK name[16] */
    /* target[16] at +0x1C stays zero for ALL_CHAT; message[64] is sanitized. */
    if(text_len)memcpy(p+0x2C,text,(int)text_len);
    p[0x2C+(int)text_len]=0;
    sendbuf(c,p,108);
    printf("  S0xCB23 social ALL_CHAT actor-broadcast uid=%u text_bytes=%u len=108\n",uid,text_len);fflush(0);
}

/* Return 1 for recognized social opcodes even when rejected, so no legacy
   fallback can manufacture an unrelated response. The caller has already run
   select_reply_control0(req control0), preserving the stable header pipeline. */
static int village_social_handle(SOCKET c,int type,int len,const unsigned char *req){
    unsigned uid;
    if(type==0xCB22){
        if(len!=12){printf("  [SOCIAL] reject CB22 len=%d\n",len);fflush(0);return 1;}
        uid=village_social_u16(req,8);
        if(uid!=VILLAGE_SOCIAL_LOCAL_UID){printf("  [SOCIAL] reject CB22 uid=%u expected=%u\n",uid,VILLAGE_SOCIAL_LOCAL_UID);fflush(0);return 1;}
        if(!village_social_valid_emotion((unsigned)req[0x0A],(unsigned)req[0x0B])){printf("  [SOCIAL] reject CB22 code/category=%u/%u\n",(unsigned)req[0x0A],(unsigned)req[0x0B]);fflush(0);return 1;}
        village_social_send_cb22(c,uid,(unsigned)req[0x0A],(unsigned)req[0x0B]);return 1;
    }
    if(type==0xC37A){
        char p[4096];
        if(len!=12){printf("  [SOCIAL] reject C37A len=%d\n",len);fflush(0);return 1;}
        mkpkt(p,0xC37B,24,1);stable_profile_write_c37b_balances(p);sendbuf(c,p,24);
        printf("  S0xC37B MY_INFO coin_hans+nana_cash len=24 (not face)\n");fflush(0);return 1;
    }    if(type==0xCB23){
        unsigned n=0;
        if(len!=108){printf("  [SOCIAL] reject CB23 len=%d\n",len);fflush(0);return 1;}
        uid=village_social_u16(req,8);
        if(uid!=VILLAGE_SOCIAL_LOCAL_UID){printf("  [SOCIAL] reject CB23 uid=%u expected=%u\n",uid,VILLAGE_SOCIAL_LOCAL_UID);fflush(0);return 1;}
        if(village_social_u16(req,0x0A)!=1000u){printf("  [SOCIAL] reject CB23 chat_type=%u (only captured ALL_CHAT=1000 enabled)\n",village_social_u16(req,0x0A));fflush(0);return 1;}
        if(!village_social_gbk_zlen(req+0x2C,64u,&n) || n==0u){printf("  [SOCIAL] reject CB23 invalid/empty GBK text\n");fflush(0);return 1;}
        village_social_send_cb23_all(c,uid,req+0x2C,n);return 1;
    }
    return 0;
}
#endif