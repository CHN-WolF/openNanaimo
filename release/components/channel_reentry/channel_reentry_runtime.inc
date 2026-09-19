#ifndef NANAIMO_CHANNEL_REENTRY_CHANNEL_REENTRY_RUNTIME_INC
#define NANAIMO_CHANNEL_REENTRY_CHANNEL_REENTRY_RUNTIME_INC

#define CHANNEL_REENTRY_CHANNEL_REENTRY_PENDING 16
#define CHANNEL_REENTRY_CHANNEL_REENTRY_INTENT_MS 30000u
#define CHANNEL_REENTRY_CHANNEL_REENTRY_CLOSE_GRACE_MS 150u
#define CHANNEL_REENTRY_CHANNEL_REENTRY_FREE_WAIT_MS 3000u
struct channel_reentry_channel_reentry_record {
    int active,slot;
    unsigned ip,serial,tick;
    struct multiplayer_profile profile;
};
static struct channel_reentry_channel_reentry_record g_channel_reentry_reentry[CHANNEL_REENTRY_CHANNEL_REENTRY_PENDING];
static unsigned g_channel_reentry_reentry_serial=0u;

static int channel_reentry_tick_age_within(unsigned now,unsigned then,unsigned limit){return (unsigned)(now-then)<=limit;}
static void multi_channel_reentry_mark_unlocked(unsigned ip){
    int i,match=-1,matches=0,store=-1;unsigned oldest=0xFFFFFFFFu,now=tickms();
    for(i=0;i<CHANNEL_REENTRY_CHANNEL_REENTRY_PENDING;i++){
        if(g_channel_reentry_reentry[i].active&&!channel_reentry_tick_age_within(now,g_channel_reentry_reentry[i].tick,CHANNEL_REENTRY_CHANNEL_REENTRY_INTENT_MS))g_channel_reentry_reentry[i].active=0;
        if(!g_channel_reentry_reentry[i].active&&store<0)store=i;
        else if(g_channel_reentry_reentry[i].active&&g_channel_reentry_reentry[i].serial<oldest){oldest=g_channel_reentry_reentry[i].serial;if(store<0)store=i;}
    }
    for(i=0;i<MULTI_MAX_PLAYERS;i++)if(g_proxy[i].in_use&&g_proxy[i].peer_ip==ip&&g_multi_backend_active[i]&&g_multi_conn[i].active){match=i;matches++;}
    if(matches!=1){printf("  [CHANNEL_REENTRY] mark ip=0x%08X matches=%d -> no preferred slot\n",ip,matches);fflush(0);return;}
    if(store<0)store=0;
    g_channel_reentry_reentry[store].active=1;g_channel_reentry_reentry[store].slot=match;g_channel_reentry_reentry[store].ip=ip;g_channel_reentry_reentry[store].serial=++g_channel_reentry_reentry_serial;g_channel_reentry_reentry[store].tick=now;g_channel_reentry_reentry[store].profile=g_multi_conn[match].profile;
    printf("  [CHANNEL_REENTRY] mark ip=0x%08X slot=%d uid=%u serial=%u transport=%d stopping=%d\n",ip,match,g_multi_conn[match].uid,g_channel_reentry_reentry[store].serial,g_multi_transport_alive[match],g_proxy[match].stopping);fflush(0);
}
static int channel_reentry_take_channel_reentry_unlocked(unsigned ip,struct multiplayer_profile*out,unsigned*serial){
    int i,best=-1;unsigned order=0xFFFFFFFFu,now=tickms();
    for(i=0;i<CHANNEL_REENTRY_CHANNEL_REENTRY_PENDING;i++){
        if(g_channel_reentry_reentry[i].active&&!channel_reentry_tick_age_within(now,g_channel_reentry_reentry[i].tick,CHANNEL_REENTRY_CHANNEL_REENTRY_INTENT_MS))g_channel_reentry_reentry[i].active=0;
        if(g_channel_reentry_reentry[i].active&&g_channel_reentry_reentry[i].ip==ip&&g_channel_reentry_reentry[i].serial<order){best=i;order=g_channel_reentry_reentry[i].serial;}
    }
    if(best<0)return -1;
    i=g_channel_reentry_reentry[best].slot;if(out)*out=g_channel_reentry_reentry[best].profile;if(serial)*serial=g_channel_reentry_reentry[best].serial;g_channel_reentry_reentry[best].active=0;return i;
}
static int channel_reentry_wait_reentry_slot(int idx,unsigned *waited){
    unsigned start=tickms(),now;int closing=0,free_now=0;
    for(;;){
        multiplayer_global_lock();
        if(idx>=0&&idx<MULTI_MAX_PLAYERS){free_now=!g_proxy[idx].in_use&&!g_multi_backend_active[idx];closing=free_now||g_proxy[idx].stopping||!g_multi_transport_alive[idx];}
        multiplayer_global_unlock();
        now=tickms();if(free_now){if(waited)*waited=(unsigned)(now-start);return 1;}
        if(!closing&&(unsigned)(now-start)>CHANNEL_REENTRY_CHANNEL_REENTRY_CLOSE_GRACE_MS){if(waited)*waited=(unsigned)(now-start);return 0;}
        if((unsigned)(now-start)>CHANNEL_REENTRY_CHANNEL_REENTRY_FREE_WAIT_MS){if(waited)*waited=(unsigned)(now-start);return 0;}
        sleep(1);
    }
}
static void multi_proxy_listener(void*unused){
    SOCKET s=pS(AF_INET,SOCK_STREAM,0);struct sockaddr_in a,peer;int i,peer_len;
    memset(&a,0,sizeof(a));a.sin_family=AF_INET;a.sin_port=(unsigned short)(((MULTI_FRONT_PORT&0xFF)<<8)|((MULTI_FRONT_PORT>>8)&0xFF));a.sin_addr=0x0100007Fu; /* 127.0.0.1: local-only listener */
    if(pB(s,&a,sizeof(a))!=0){printf("  [MULTI_PROXY] bind fail front=%d\n",MULTI_FRONT_PORT);fflush(0);return;}
    pL(s,8);printf("  [MULTI_PROXY] listening front=%d back=%d..%d channel_reentry=channel_reentry\n",MULTI_FRONT_PORT,MULTI_BACK_BASE,MULTI_BACK_BASE+MULTI_MAX_PLAYERS-1);fflush(0);
    for(;;){
        SOCKET front,back;struct sockaddr_in d;struct multiplayer_profile carry;int idx=-1,preferred=-1,gen,have_carry=0;unsigned peer_port,accept_id,serial=0,waited=0;
        peer_len=sizeof(peer);memset(&peer,0,sizeof(peer));front=pA(s,&peer,&peer_len);if(front==INVALID_SOCKET)break;peer_port=peer_endpoint_host_port(peer.sin_port);accept_id=++g_peer_endpoint_accept_serial;
        printf("  [PEER] accept service=GS_FRONT accept=%u socket=%u src=",accept_id,(unsigned)front);peer_endpoint_print_endpoint(peer.sin_addr,peer_port);printf("\n");fflush(0);
        multiplayer_global_lock();preferred=channel_reentry_take_channel_reentry_unlocked(peer.sin_addr,&carry,&serial);multiplayer_global_unlock();
        if(preferred>=0){
            if(channel_reentry_wait_reentry_slot(preferred,&waited)){idx=preferred;have_carry=1;printf("  [CHANNEL_REENTRY] preferred-ready accept=%u serial=%u slot=%d wait_ms=%u\n",accept_id,serial,idx,waited);fflush(0);}
            else{printf("  [CHANNEL_REENTRY] preferred-timeout accept=%u serial=%u slot=%d wait_ms=%u -> normal allocation\n",accept_id,serial,preferred,waited);fflush(0);}
        }
        multiplayer_global_lock();
        if(idx>=0&&g_proxy[idx].in_use)idx=-1;
        if(idx<0)for(i=0;i<MULTI_MAX_PLAYERS;i++)if(!g_proxy[i].in_use){idx=i;break;}
        if(idx>=0){
            g_proxy[idx].in_use=1;g_proxy[idx].stopping=0;g_proxy[idx].pumps=2;g_proxy[idx].io_done=0;g_proxy[idx].generation++;g_proxy[idx].backend_port=MULTI_BACK_BASE+idx;g_proxy[idx].front=front;g_proxy[idx].peer_ip=peer.sin_addr;g_peer_endpoint_peer_ip[idx]=peer.sin_addr;g_peer_endpoint_peer_port[idx]=peer_port;g_peer_endpoint_accept_id[idx]=accept_id;g_multi_slot_join_order[idx]=++g_multi_proxy_accept_serial;
            if(have_carry){g_multi_slot_profile[idx]=carry;g_multi_slot_profile_valid[idx]=1;}else if(multi_take_pending_profile(peer.sin_addr,&g_multi_slot_profile[idx]))g_multi_slot_profile_valid[idx]=1;
        }
        multiplayer_global_unlock();
        if(idx<0){printf("  [MULTI_PROXY] full; reject\n");fflush(0);pC(front);continue;}
        back=pS(AF_INET,SOCK_STREAM,0);memset(&d,0,sizeof(d));d.sin_family=AF_INET;d.sin_port=(unsigned short)((((MULTI_BACK_BASE+idx)&0xFF)<<8)|(((MULTI_BACK_BASE+idx)>>8)&0xFF));d.sin_addr=0x0100007Fu;
        if(pConn(back,&d,sizeof(d))!=0){int err=pErr?pErr():0;printf("  [MULTI_PROXY] backend connect fail accept=%u slot=%d err=%d src=",accept_id,idx,err);peer_endpoint_print_endpoint(peer.sin_addr,peer_port);printf("\n");fflush(0);pC(front);pC(back);multiplayer_global_lock();g_proxy[idx].in_use=0;g_peer_endpoint_peer_ip[idx]=g_peer_endpoint_peer_port[idx]=g_peer_endpoint_accept_id[idx]=0u;g_multi_slot_profile_valid[idx]=0;multiplayer_global_unlock();continue;}
        multiplayer_global_lock();g_proxy[idx].back=back;gen=g_proxy[idx].generation;g_proxy_args[idx][0].slot=idx;g_proxy_args[idx][0].direction=0;g_proxy_args[idx][0].generation=gen;g_proxy_args[idx][1].slot=idx;g_proxy_args[idx][1].direction=1;g_proxy_args[idx][1].generation=gen;multiplayer_global_unlock();
        _beginthread(multi_proxy_pump,0,&g_proxy_args[idx][0]);_beginthread(multi_proxy_pump,0,&g_proxy_args[idx][1]);
        printf("  [MULTI_PROXY] assign accept=%u gen=%d slot=%d uid=%u backend=%d front=%u back=%u reentry=%d serial=%u src=",accept_id,gen,idx,21u+(unsigned)idx,MULTI_BACK_BASE+idx,(unsigned)front,(unsigned)back,have_carry,serial);peer_endpoint_print_endpoint(peer.sin_addr,peer_port);printf("\n");fflush(0);
    }
    pC(s);(void)unused;
}
static void multiplayer_start_listeners(void){int i;multiplayer_shared_combat_init();for(i=0;i<MULTI_MAX_PLAYERS;i++)_beginthread(gs_thread,0,(void*)(MULTI_BACK_BASE+i));sleep(100);_beginthread(multi_profile_listener,0,0);_beginthread(multi_proxy_listener,0,0);}
#endif
