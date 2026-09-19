#ifndef NANAIMO_MULTIPLAYER_VILLAGE_SOCIAL_VILLAGE_SOCIAL_INC
#define NANAIMO_MULTIPLAYER_VILLAGE_SOCIAL_VILLAGE_SOCIAL_INC

/* Network social routing. The legacy stable_village_social handler remains the
   Stand_Alone UID1 path. Network source identity is the per-connection scene
   UID and peer delivery is restricted to an instantiated actor in the same
   village selector/page. Every target gets a fresh header/sequence/checksum. */
static int multi_social_target_visible(int src,int target){
    if(target==src)return 1;
    return g_multi_conn[src].village_actor_ready &&
           g_multi_conn[target].village_actor_ready &&
           multi_same_village_idx(src,target);
}
static void multi_social_send_cb22_idx(int target,int src,unsigned code,unsigned category){
    char p[4096];
    if(target<0||target>=MULTI_MAX_PLAYERS||!g_multi_conn[target].active)return;
    if(target!=src)multi_switch_to(target,src);
    mkpkt(p,0xCB22,12,1);
    stable_resource_put16(p,8,g_multi_conn[src].uid);
    p[0x0A]=(char)code;p[0x0B]=(char)category;
    sendbuf(g_multi_conn[target].socket,p,12);
    if(target!=src)multi_switch_back(src,target);
}
static void multi_social_send_cb23_idx(int target,int src,const unsigned char*text,unsigned text_len){
    char p[4096];unsigned n;
    if(target<0||target>=MULTI_MAX_PLAYERS||!g_multi_conn[target].active)return;
    if(target!=src)multi_switch_to(target,src);
    mkpkt(p,0xCB23,108,1);
    stable_resource_put16(p,8,g_multi_conn[src].uid);
    stable_resource_put16(p,0x0A,1000u);
    n=g_multi_conn[src].profile.name_len;if(n>15u)n=15u;
    if(n)memcpy(p+0x0C,g_multi_conn[src].profile.name,(int)n);
    if(text_len)memcpy(p+0x2C,text,(int)text_len);
    p[0x2C+(int)text_len]=0;
    sendbuf(g_multi_conn[target].socket,p,108);
    if(target!=src)multi_switch_back(src,target);
}
/* Return 1 for recognized CB22/CB23 even on rejection, preventing the fixed
   UID1 legacy handler from consuming Network requests. */
static int multiplayer_village_social_handle(int type,int len,const unsigned char*req){
    int i,src=g_multi_current,deliveries=0;unsigned uid,n=0;
    if(type!=0xCB22&&type!=0xCB23)return 0;
    if(src<0||src>=MULTI_MAX_PLAYERS||!g_multi_conn[src].active)return 1;
    if((type==0xCB22&&len!=12)||(type==0xCB23&&len!=108)){
        printf("  [MULTI_SOCIAL] reject type=0x%04X len=%d uid=%u\n",type,len,g_multi_conn[src].uid);fflush(0);return 1;
    }
    uid=village_social_u16(req,8);
    if(uid!=g_multi_conn[src].uid){
        printf("  [MULTI_SOCIAL] reject type=0x%04X uid=%u expected_dynamic=%u\n",type,uid,g_multi_conn[src].uid);fflush(0);return 1;
    }
    if(type==0xCB22){
        if(!village_social_valid_emotion((unsigned)req[0x0A],(unsigned)req[0x0B])){
            printf("  [MULTI_SOCIAL] reject CB22 code/category=%u/%u uid=%u\n",(unsigned)req[0x0A],(unsigned)req[0x0B],uid);fflush(0);return 1;
        }
        for(i=0;i<MULTI_MAX_PLAYERS;i++)if(g_multi_conn[i].active&&g_multi_transport_alive[i]&&multi_social_target_visible(src,i)){multi_social_send_cb22_idx(i,src,(unsigned)req[0x0A],(unsigned)req[0x0B]);deliveries++;}
        printf("  [MULTI_SOCIAL] CB22 uid=%u code=%u category=%u deliveries=%d selector=%u page=%u\n",uid,(unsigned)req[0x0A],(unsigned)req[0x0B],deliveries,g_multi_conn[src].village_selector,g_multi_conn[src].village_page);fflush(0);return 1;
    }
    if(village_social_u16(req,0x0A)!=1000u){printf("  [MULTI_SOCIAL] reject CB23 chat_type=%u uid=%u\n",village_social_u16(req,0x0A),uid);fflush(0);return 1;}
    if(!village_social_gbk_zlen(req+0x2C,64u,&n)||n==0u){printf("  [MULTI_SOCIAL] reject CB23 invalid/empty GBK uid=%u\n",uid);fflush(0);return 1;}
    for(i=0;i<MULTI_MAX_PLAYERS;i++)if(g_multi_conn[i].active&&g_multi_transport_alive[i]&&multi_social_target_visible(src,i)){multi_social_send_cb23_idx(i,src,req+0x2C,n);deliveries++;}
    printf("  [MULTI_SOCIAL] CB23 uid=%u text_bytes=%u deliveries=%d selector=%u page=%u\n",uid,n,deliveries,g_multi_conn[src].village_selector,g_multi_conn[src].village_page);fflush(0);return 1;
}
#endif