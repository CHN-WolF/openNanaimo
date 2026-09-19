#ifndef NANAIMO_MULTIPLAYER_RUNTIME_PEER_ENDPOINT_INC
#define NANAIMO_MULTIPLAYER_RUNTIME_PEER_ENDPOINT_INC
/* PEER_ENDPOINT keeps START_EPOCH start epochs, but replaces the CFD4 peer record and
   the front/profile listeners so the real client endpoint is retained. */
#define multiplayer_send_peer_list_current multiplayer_send_peer_list_current_start_epoch_legacy
#define multi_profile_listener multi_profile_listener_start_epoch_legacy
#define multi_proxy_listener multi_proxy_listener_start_epoch_legacy
#define multiplayer_start_listeners multiplayer_start_listeners_start_epoch_legacy
#include "start_runtime.inc"
#undef multiplayer_start_listeners
#undef multi_proxy_listener
#undef multi_profile_listener
#undef multiplayer_send_peer_list_current

#define PEER_ENDPOINT_P2P_UDP_PORT 3534u
static unsigned g_peer_endpoint_peer_ip[MULTI_MAX_PLAYERS];
static unsigned g_peer_endpoint_peer_port[MULTI_MAX_PLAYERS];
static unsigned g_peer_endpoint_accept_id[MULTI_MAX_PLAYERS];
static unsigned g_peer_endpoint_accept_serial=0u;

static unsigned peer_endpoint_host_port(unsigned short network_port){return ((unsigned)(network_port&0x00FFu)<<8)|((unsigned)(network_port&0xFF00u)>>8);}
static void peer_endpoint_print_ipv4(unsigned ip){const unsigned char*b=(const unsigned char*)&ip;printf("%u.%u.%u.%u",(unsigned)b[0],(unsigned)b[1],(unsigned)b[2],(unsigned)b[3]);}
static void peer_endpoint_print_endpoint(unsigned ip,unsigned port){if(!ip){printf("unknown");return;}peer_endpoint_print_ipv4(ip);printf(":%u",port);}
static int peer_endpoint_append_octet(char*p,int n,unsigned v){if(v>=100u)p[n++]=(char)('0'+v/100u);if(v>=10u)p[n++]=(char)('0'+(v/10u)%10u);p[n++]=(char)('0'+v%10u);return n;}
static void peer_endpoint_write_ipv4_text(char*p,int off,unsigned ip){const unsigned char*b=(const unsigned char*)&ip;int n=0,i;memset(p+off,0,16);for(i=0;i<4;i++){if(i)p[off+n++]='.';n=peer_endpoint_append_octet(p+off,n,(unsigned)b[i]);}}
static unsigned peer_endpoint_peer_ip_idx(int idx){return idx>=0&&idx<MULTI_MAX_PLAYERS?g_peer_endpoint_peer_ip[idx]:0u;}
static unsigned peer_endpoint_peer_port_idx(int idx){return idx>=0&&idx<MULTI_MAX_PLAYERS?g_peer_endpoint_peer_port[idx]:0u;}
static unsigned peer_endpoint_accept_id_idx(int idx){return idx>=0&&idx<MULTI_MAX_PLAYERS?g_peer_endpoint_accept_id[idx]:0u;}
static void peer_endpoint_log_current_endpoint(void){int idx=g_multi_current;printf(" accept=%u src=",peer_endpoint_accept_id_idx(idx));peer_endpoint_print_endpoint(peer_endpoint_peer_ip_idx(idx),peer_endpoint_peer_port_idx(idx));}

/* Original game endpoint teamplay wire, both retained views:
   record+2 WORD peer UID, record+4 char[16] peer IPv4, record+0x14 DWORD
   peer UDP port (3534 in both captures). START_EPOCH incorrectly wrote constant40
   at +2, adapter IP for every peer, WORD12050 at +0x14 and UID at +0x16. */
static void multiplayer_send_peer_list_current(void){
    char p[4096];int i,n=0,src=g_multi_current,r;unsigned ip;
    if(src<0)return;
    mkpkt(p,0xCFD4,0x0C+0x18*(MULTI_MAX_PLAYERS-1),1);p[8]=(char)0x90;p[9]=1;
    for(i=0;i<MULTI_MAX_PLAYERS;i++)if(i!=src&&g_multi_conn[i].active&&g_multi_transport_alive[i]&&g_multi_conn[i].room_active){
        r=0x0C+n*0x18;p[r+1]=(char)n;stable_resource_put16(p,r+2,g_multi_conn[i].uid);
        ip=peer_endpoint_peer_ip_idx(i);if(ip)peer_endpoint_write_ipv4_text(p,r+4,ip);else stable_write_advertised_ip(p,r+4);
        stable_put32(p,r+0x14,PEER_ENDPOINT_P2P_UDP_PORT);n++;
    }
    p[0x0A]=(char)n;p[0x0B]=0;stable_resource_put16(p,4,0x0C+n*0x18);sendbuf(g_multi_conn[src].socket,p,0x0C+n*0x18);
    printf("  S0xCFD4 PEER_ENDPOINT peers=%d len=%u target_uid=%u",n,0x0C+n*0x18,g_multi_conn[src].uid);peer_endpoint_log_current_endpoint();printf(" p2p_udp=%u\n",PEER_ENDPOINT_P2P_UDP_PORT);fflush(0);
}

static void multi_profile_listener(void*unused){
    SOCKET s=pS(AF_INET,SOCK_STREAM,0);struct sockaddr_in a,peer;int plen;
    memset(&a,0,sizeof(a));a.sin_family=AF_INET;a.sin_port=(unsigned short)(((MULTI_PROFILE_PORT&0xFF)<<8)|((MULTI_PROFILE_PORT>>8)&0xFF));a.sin_addr=0x0100007Fu; /* 127.0.0.1: local-only listener */
    if(pB(s,&a,sizeof(a))!=0){printf("  [MULTI_PROFILE] bind fail port=%d\n",MULTI_PROFILE_PORT);fflush(0);return;}
    pL(s,8);printf("  [MULTI_PROFILE] listening port=%d\n",MULTI_PROFILE_PORT);fflush(0);
    for(;;){SOCKET c;unsigned len;char text[4096],ack[3];struct multiplayer_profile prof;int stored;unsigned peer_port;
        plen=sizeof(peer);memset(&peer,0,sizeof(peer));c=pA(s,&peer,&plen);if(c==INVALID_SOCKET)break;peer_port=peer_endpoint_host_port(peer.sin_port);
        printf("  [PEER] accept service=PROFILE socket=%u src=",(unsigned)c);peer_endpoint_print_endpoint(peer.sin_addr,peer_port);printf(" ip_key=0x%08X\n",peer.sin_addr);fflush(0);
        if(!multi_recv_exact(c,(char*)&len,4)||len>=sizeof(text)||!multi_recv_exact(c,text,(int)len)){printf("  [PEER] close service=PROFILE socket=%u src=",(unsigned)c);peer_endpoint_print_endpoint(peer.sin_addr,peer_port);printf(" reason=short-upload\n");fflush(0);pC(c);continue;}
        text[len]=0;multiplayer_global_lock();multi_capture_profile(&prof);multi_parse_profile_text(&prof,text);stored=multi_store_pending_profile(peer.sin_addr,&prof);multiplayer_global_unlock();ack[0]=stored?'O':'N';ack[1]=stored?'K':'O';ack[2]='\n';pSd(c,ack,3,0);
        printf("  [PEER] profile service=PROFILE socket=%u src=",(unsigned)c);peer_endpoint_print_endpoint(peer.sin_addr,peer_port);printf(" stored=%d bytes=%u\n",stored,len);fflush(0);pC(c);
    }
    pC(s);(void)unused;
}

static void multi_proxy_listener(void*unused){
    SOCKET s=pS(AF_INET,SOCK_STREAM,0);struct sockaddr_in a,peer;int i,peer_len;
    memset(&a,0,sizeof(a));a.sin_family=AF_INET;a.sin_port=(unsigned short)(((MULTI_FRONT_PORT&0xFF)<<8)|((MULTI_FRONT_PORT>>8)&0xFF));a.sin_addr=0x0100007Fu; /* 127.0.0.1: local-only listener */
    if(pB(s,&a,sizeof(a))!=0){printf("  [MULTI_PROXY] bind fail front=%d\n",MULTI_FRONT_PORT);fflush(0);return;}
    pL(s,8);printf("  [MULTI_PROXY] listening front=%d back=%d..%d\n",MULTI_FRONT_PORT,MULTI_BACK_BASE,MULTI_BACK_BASE+MULTI_MAX_PLAYERS-1);fflush(0);
    for(;;){SOCKET front,back;struct sockaddr_in d;int idx=-1,gen;unsigned peer_port,accept_id;
        peer_len=sizeof(peer);memset(&peer,0,sizeof(peer));front=pA(s,&peer,&peer_len);if(front==INVALID_SOCKET)break;peer_port=peer_endpoint_host_port(peer.sin_port);accept_id=++g_peer_endpoint_accept_serial;if(!accept_id)accept_id=++g_peer_endpoint_accept_serial;
        printf("  [PEER] accept service=GS_FRONT accept=%u socket=%u src=",accept_id,(unsigned)front);peer_endpoint_print_endpoint(peer.sin_addr,peer_port);printf("\n");fflush(0);
        multiplayer_global_lock();for(i=0;i<MULTI_MAX_PLAYERS;i++)if(!g_proxy[i].in_use){idx=i;g_proxy[i].in_use=1;g_proxy[i].stopping=0;g_proxy[i].pumps=2;g_proxy[i].io_done=0;g_proxy[i].generation++;g_proxy[i].backend_port=MULTI_BACK_BASE+i;g_proxy[i].front=front;g_proxy[i].peer_ip=peer.sin_addr;g_peer_endpoint_peer_ip[i]=peer.sin_addr;g_peer_endpoint_peer_port[i]=peer_port;g_peer_endpoint_accept_id[i]=accept_id;g_multi_slot_join_order[i]=++g_multi_proxy_accept_serial;if(multi_take_pending_profile(peer.sin_addr,&g_multi_slot_profile[i]))g_multi_slot_profile_valid[i]=1;break;}multiplayer_global_unlock();
        if(idx<0){printf("  [MULTI_PROXY] full reject accept=%u src=",accept_id);peer_endpoint_print_endpoint(peer.sin_addr,peer_port);printf("\n");fflush(0);pC(front);continue;}
        back=pS(AF_INET,SOCK_STREAM,0);memset(&d,0,sizeof(d));d.sin_family=AF_INET;d.sin_port=(unsigned short)((((MULTI_BACK_BASE+idx)&0xFF)<<8)|(((MULTI_BACK_BASE+idx)>>8)&0xFF));d.sin_addr=0x0100007Fu;
        if(pConn(back,&d,sizeof(d))!=0){int err=pErr?pErr():0;printf("  [MULTI_PROXY] backend connect fail accept=%u slot=%d err=%d src=",accept_id,idx,err);peer_endpoint_print_endpoint(peer.sin_addr,peer_port);printf("\n");fflush(0);pC(front);pC(back);multiplayer_global_lock();g_proxy[idx].in_use=0;g_peer_endpoint_peer_ip[idx]=g_peer_endpoint_peer_port[idx]=g_peer_endpoint_accept_id[idx]=0u;multiplayer_global_unlock();continue;}
        multiplayer_global_lock();g_proxy[idx].back=back;gen=g_proxy[idx].generation;g_proxy_args[idx][0].slot=idx;g_proxy_args[idx][0].direction=0;g_proxy_args[idx][0].generation=gen;g_proxy_args[idx][1].slot=idx;g_proxy_args[idx][1].direction=1;g_proxy_args[idx][1].generation=gen;multiplayer_global_unlock();
        _beginthread(multi_proxy_pump,0,&g_proxy_args[idx][0]);_beginthread(multi_proxy_pump,0,&g_proxy_args[idx][1]);
        printf("  [MULTI_PROXY] assign accept=%u gen=%d slot=%d uid=%u backend=%d front=%u back=%u src=",accept_id,gen,idx,21u+(unsigned)idx,MULTI_BACK_BASE+idx,(unsigned)front,(unsigned)back);peer_endpoint_print_endpoint(peer.sin_addr,peer_port);printf("\n");fflush(0);
    }
    pC(s);(void)unused;
}
static void multiplayer_start_listeners(void){int i;multiplayer_shared_combat_init();for(i=0;i<MULTI_MAX_PLAYERS;i++)_beginthread(gs_thread,0,(void*)(MULTI_BACK_BASE+i));sleep(100);_beginthread(multi_profile_listener,0,0);_beginthread(multi_proxy_listener,0,0);}
#endif
