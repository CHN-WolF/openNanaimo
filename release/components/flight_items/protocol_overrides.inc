#ifndef NANAIMO_FLIGHT_ITEMS_PROTOCOL_OVERRIDES_INC
#define NANAIMO_FLIGHT_ITEMS_PROTOCOL_OVERRIDES_INC
static unsigned g_flight_items_cf80_map_hint=0u,g_flight_items_cf80_uid_hint=21u;
static void flight_items_cf80_set_hints(unsigned map_index,unsigned uid){g_flight_items_cf80_map_hint=map_index;g_flight_items_cf80_uid_hint=uid?uid:21u;}
/* Static client closure: the CF80 handler consumes through DWORD +0x300.
 * +0x0A/+0x0C are 150 signed scatter-coordinate pairs, +0x262 is a
 * 20-byte room UID vector, +0x276 is the 50-entry random pickup schedule,
 * and +0x2A8 is the 50-entry money-value code schedule. */
static void send_cf80_start(SOCKET c){
    static const unsigned char money_codes[10]={0u,1u,0u,2u,0u,0u,1u,0u,2u,0u};
    char p[4096];unsigned i;mkpkt(p,0xCF80,0x304,1);p[8]=1;p[9]=(char)(g_flight_items_cf80_map_hint&0xFFu);
    for(i=0;i<150u;i++){
        unsigned x=50u+((i*137u+g_flight_items_cf80_map_hint*29u)%700u);
        unsigned y=50u+((i*83u+g_flight_items_cf80_map_hint*17u)%500u);
        stable_resource_put16(p,0x0A+(int)(4u*i),x);stable_resource_put16(p,0x0C+(int)(4u*i),y);
    }
    for(i=0;i<20u;i++)p[0x262+i]=(char)(i<MULTI_MAX_PLAYERS?(21u+i):0u);
    p[0x262]=(char)(g_flight_items_cf80_uid_hint&0xFFu);
    for(i=0;i<50u;i++)p[0x276+i]=(char)(1u+(i%4u));
    for(i=0;i<50u;i++)p[0x2A8+i]=(char)money_codes[i%10u];
    /* +0x2DA..+0x303 are optional flags/two 16-byte event rows. mkpkt
       zero-initializes them, satisfying every statically consumed byte. */
    sendbuf(c,p,0x304);
    printf("  S0xCF80 FLIGHT_ITEMS full-game-data ans=1 map=%u uid0=%u random_types=uniform-1..4 money_codes=60pct10/20pct50/20pct100 len=772 t=%lds\n",g_flight_items_cf80_map_hint,g_flight_items_cf80_uid_hint,sec());fflush(0);
}
#endif
