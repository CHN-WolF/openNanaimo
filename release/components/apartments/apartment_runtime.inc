#ifndef NANAIMO_APARTMENTS_APARTMENT_RUNTIME_INC
#define NANAIMO_APARTMENTS_APARTMENT_RUNTIME_INC
#include "../interiors/interior_catalog.inc"
extern unsigned __attribute__((cdecl)) fread(void*,unsigned,unsigned,void*);
extern unsigned __attribute__((cdecl)) fwrite(const void*,unsigned,unsigned,void*);
#define APARTMENT_MAX_ITEMS 254u
#define APARTMENT_STATE_PATH "nanaimo_apartment_state_v1.dat"
#define APARTMENT_STATE_TMP  "nanaimo_apartment_state_v1.new"
struct apartment_item_row{unsigned code;unsigned short index;unsigned char placed,type;short x,y;unsigned char z,mirror;};
struct apartment_disk{unsigned magic,version,count;struct apartment_item_row item[APARTMENT_MAX_ITEMS];};
static struct apartment_disk g_apartment;
static int g_apartment_loaded=0;
static void apartment_defaults(void){memset(&g_apartment,0,sizeof(g_apartment));g_apartment.magic=0x31545041u;g_apartment.version=1u;}
static void apartment_load(void){FILE*f;if(g_apartment_loaded)return;g_apartment_loaded=1;apartment_defaults();f=fopen(APARTMENT_STATE_PATH,"rb");if(f){struct apartment_disk d;if(fread(&d,1,sizeof(d),f)==sizeof(d)&&d.magic==0x31545041u&&d.version==1u&&d.count<=APARTMENT_MAX_ITEMS)g_apartment=d;fclose(f);}printf("  [APARTMENT] load count=%u\n",g_apartment.count);fflush(0);}
/* Per-file replace keeps the previous file if replacement fails. Cross-file
   inventory+currency power-loss atomicity is NOT claimed. */
extern int __attribute__((stdcall)) MoveFileExA(const char*,const char*,unsigned long);
static int apartment_save(void){
 FILE*f=fopen(APARTMENT_STATE_TMP,"wb");int ok;if(!f)return 0;
 ok=fwrite(&g_apartment,1,sizeof(g_apartment),f)==sizeof(g_apartment);
 if(fflush(f)!=0)ok=0;if(fclose(f)!=0)ok=0;
 if(!ok){remove(APARTMENT_STATE_TMP);return 0;}
 if(!MoveFileExA(APARTMENT_STATE_TMP,APARTMENT_STATE_PATH,9u)){remove(APARTMENT_STATE_TMP);return 0;}
 return 1;
}
static int apartment_find_index(unsigned idx){unsigned i;for(i=0;i<g_apartment.count;i++)if(g_apartment.item[i].index==idx)return (int)i;return -1;}
static unsigned apartment_alloc_index(void){unsigned x;for(x=1;x<255u;x++)if(apartment_find_index(x)<0)return x;return 0;}
static void apartment_put_room_row(char*p,unsigned off,const struct apartment_item_row*r){stable_put32(p,(int)off,r->code);stable_resource_put16(p,(int)off+4,(unsigned short)r->x);stable_resource_put16(p,(int)off+6,(unsigned short)r->y);p[off+8]=(char)r->z;p[off+9]=(char)r->type;p[off+10]=(char)r->mirror;p[off+11]=(char)r->index;}
/* C409 DWORD+8=10/30 are explicit client consumer modes. The scene handlers
   0x541B30 / 0x59F660 must skip these C40A modes. Preserve the prior room path
   (0) for other/uninitialized room tails; never echo arbitrary bytes as a mode.
   This is request-local, with no sticky selector across UI or TCP epochs. */
static unsigned apartment_c40a_consumer(unsigned request_mode){return request_mode==10u||request_mode==30u?request_mode:0u;}
static void apartment_send_c40a(SOCKET c,unsigned request_mode){char p[4096];unsigned i,n;apartment_load();n=g_apartment.count;if(n>255u)n=255u;mkpkt(p,0xC40A,12+(int)(12u*n),1);p[8]=(char)apartment_c40a_consumer(request_mode);p[9]=1;p[10]=0;p[11]=(char)n;for(i=0;i<n;i++){unsigned off=12u+12u*i;stable_put32(p,(int)off,g_apartment.item[i].code);stable_resource_put16(p,(int)off+4,g_apartment.item[i].placed?1u:0u);stable_resource_put16(p,(int)off+6,g_apartment.item[i].index);stable_put32(p,(int)off+8,0u);}sendbuf(c,p,12+(int)(12u*n));printf("  S0xC40A apartment inventory request_mode=%u consumer=%u rows=%u len=%u t=%lds\n",request_mode,(unsigned char)p[8],n,12u+12u*n,sec());fflush(0);}
static void apartment_send_c424(SOCKET c){char p[4096];unsigned i,n=0;const struct apartment_item_row*floor=0,*wall=0;apartment_load();mkpkt(p,0xC424,1044,1);stable_resource_put16(p,8,2000u);for(i=0;i<g_apartment.count;i++)if(g_apartment.item[i].placed){const struct apartment_item_row*r=&g_apartment.item[i];if(r->type==0)floor=r;else if(r->type==1)wall=r;else if(n<84u){apartment_put_room_row(p,12u+12u*n,r);n++;}}stable_resource_put16(p,10,n);if(floor)apartment_put_room_row(p,1020u,floor);if(wall)apartment_put_room_row(p,1032u,wall);sendbuf(c,p,1044);printf("  S0xC424 apartment room-state objects=%u floor=%u wall=%u len=1044 t=%lds\n",n,floor?floor->code:0u,wall?wall->code:0u,sec());fflush(0);}
/* C392/12 -> C393: WORD count+8, WORD final-info+10; stride12
   objects from+12. 6000 requests continuation; 2000 marks our complete snapshot.
   Floors/walls have separate C38E carriers; never include them in this array. */
static void apartment_send_c393(SOCKET c){
 char p[4096];unsigned i,n=0;apartment_load();mkpkt(p,0xC393,1020,1);
 for(i=0;i<g_apartment.count;i++)if(g_apartment.item[i].placed&&g_apartment.item[i].type>=2u&&n<84u){apartment_put_room_row(p,12u+12u*n,&g_apartment.item[i]);n++;}
 stable_resource_put16(p,8,n);stable_resource_put16(p,10,2000u);sendbuf(c,p,1020);
 printf("  S0xC393 apartment scene objects=%u final=2000 len=1020 t=%lds\n",n,sec());fflush(0);
}
static void apartment_send_c38e(SOCKET c,const unsigned char*req){char p[4096];unsigned n=0;apartment_load();mkpkt(p,0xC38E,112,1);p[8]=10;p[9]=10;stable_resource_put16(p,10,0u);while(n<16u&&n<g_stable_name_len&&g_stable_name[n]){p[12+n]=(char)g_stable_name[n];n++;}p[30]=(char)n;p[31]=0;p[32]=0;p[33]=0;p[34]=1;p[35]=0;stable_resource_put16(p,36,400u);stable_resource_put16(p,38,300u);stable_put32(p,40,400u);stable_put32(p,44,300u);for(n=0;n<g_apartment.count;n++)if(g_apartment.item[n].placed&&g_apartment.item[n].type==0)apartment_put_room_row(p,88u,&g_apartment.item[n]);for(n=0;n<g_apartment.count;n++)if(g_apartment.item[n].placed&&g_apartment.item[n].type==1)apartment_put_room_row(p,100u,&g_apartment.item[n]);sendbuf(c,p,112);printf("  S0xC38E apartment enter status=10 owner_len=%u len=112 t=%lds\n",(unsigned char)p[30],sec());fflush(0);}
static int apartment_purchase(SOCKET c,const unsigned char*f,int len){unsigned count,i,total_coin=0,total_nana=0,oldcount;stable_u64 oldcoin,oldnana;struct apartment_disk old;char p[4096];int ok=1;if(len!=216)return 0;apartment_load();count=f[15];if(!count||count>40u||g_apartment.count+count>APARTMENT_MAX_ITEMS)ok=0;old=g_apartment;oldcount=g_apartment.count;oldcoin=g_profile_coin_hans;oldnana=g_profile_nana_cash;for(i=0;i<count&&ok;i++){unsigned code=shopping_read32(f,56u+4u*i);const struct apartment_catalog_row*r=apartment_catalog_find(code);if(!r||!apartment_alloc_index())ok=0;else if(total_coin>0xFFFFFFFFu-r->coin||total_nana>0xFFFFFFFFu-r->nana)ok=0;else{total_coin+=r->coin;total_nana+=r->nana;}}
if(ok&&(g_profile_coin_hans<(stable_u64)total_coin||g_profile_nana_cash<(stable_u64)total_nana))ok=0;
if(ok){for(i=0;i<count;i++){unsigned code=shopping_read32(f,56u+4u*i),idx=apartment_alloc_index();const struct apartment_catalog_row*r=apartment_catalog_find(code);struct apartment_item_row*q=&g_apartment.item[g_apartment.count++];memset(q,0,sizeof(*q));q->code=code;q->index=(unsigned short)idx;q->type=r->type;q->x=400;q->y=300;}g_profile_coin_hans-=total_coin;g_profile_nana_cash-=total_nana;if(!apartment_save()||!shopping_state_save()){g_apartment=old;g_profile_coin_hans=oldcoin;g_profile_nana_cash=oldnana;apartment_save();shopping_state_save();ok=0;}}
mkpkt(p,0xC40C,1040,1);p[8]=(char)(ok?10:20);p[9]=0;p[10]=(char)(ok?1:0);p[11]=(char)(ok?count:0);if(ok)for(i=0;i<count;i++){unsigned off=12u+12u*i;struct apartment_item_row*q=&g_apartment.item[oldcount+i];stable_put32(p,(int)off,q->code);stable_resource_put16(p,(int)off+4,0u);stable_resource_put16(p,(int)off+6,q->index);stable_put32(p,(int)off+8,0u);}stable_resource_put64(p,1024,g_profile_coin_hans);stable_resource_put64(p,1032,g_profile_nana_cash);sendbuf(c,p,1040);printf("  S0xC40C apartment purchase success=%d count=%u coin_cost=%u nana_cost=%u inventory=%u len=1040 t=%lds\n",ok,count,total_coin,total_nana,g_apartment.count,sec());fflush(0);return 1;}
/* Validate the complete transaction on a private copy. No partial rows become
   visible on later-invalid indices/counts, excess room capacity, or save failure.
   One floor and one wall; new placement replaces the prior instance (policy). */
static int apartment_change(SOCKET c,const unsigned char*f,int len){
 unsigned on,off,i,j,objects=0,building_rows=0;unsigned char seen[255];struct apartment_disk old,next;char p[4096];int ok=1;
 if(len!=768)return 0;apartment_load();old=g_apartment;next=old;memset(seen,0,sizeof(seen));
 on=(unsigned)f[764]|((unsigned)f[765]<<8);off=(unsigned)f[766]|((unsigned)f[767]<<8);
 if(on>84u||off>84u)ok=0;
 for(i=0;i<on&&ok;i++){
  unsigned b=8u+8u*i,idx=(unsigned)f[b]|((unsigned)f[b+1]<<8);int q=apartment_find_index(idx);
  if(q<0||idx>=255u||seen[idx]||f[b+7]>1u){ok=0;break;}seen[idx]=1;
  if(next.item[q].type<2u)for(j=0;j<next.count;j++)if(j!=(unsigned)q&&next.item[j].type==next.item[q].type)next.item[j].placed=0;
  next.item[q].placed=1;next.item[q].x=(short)((unsigned)f[b+2]|((unsigned)f[b+3]<<8));
  next.item[q].y=(short)((unsigned)f[b+4]|((unsigned)f[b+5]<<8));next.item[q].z=f[b+6];next.item[q].mirror=f[b+7];
 }
 for(i=0;i<off&&ok;i++){
  unsigned idx=f[680u+i];int q=apartment_find_index(idx);
  if(q<0||idx>=255u||seen[idx]){ok=0;break;}seen[idx]=1;next.item[q].placed=0;
 }
 for(i=0;i<next.count&&ok;i++)if(next.item[i].placed&&next.item[i].type>=2u){objects++;if(next.item[i].type==4u)building_rows++;}
 /* Type4 can allocate rectangles into the scene's fixed 40-pointer array.
    Conservatively cap this catalog class until subtype-specific bounds close. */
 if(objects>84u||building_rows>40u)ok=0;
 if(ok){g_apartment=next;if(!apartment_save()){g_apartment=old;ok=0;}}
 mkpkt(p,0xC412,12,1);stable_put32(p,8,ok?2000u:1000u);sendbuf(c,p,12);
 printf("  S0xC412 apartment change success=%d take_on=%u take_off=%u objects=%u len=12 t=%lds\n",ok,on,off,objects,sec());fflush(0);return 1;
}
static int apartment_delete(SOCKET c,const unsigned char*f,int len){unsigned code,idx,i;int q,ok=0;struct apartment_disk old;char p[4096];if(len!=20)return 0;apartment_load();code=shopping_read32(f,8);idx=(unsigned)f[14]|((unsigned)f[15]<<8);q=apartment_find_index(idx);old=g_apartment;if(q>=0&&g_apartment.item[q].code==code){for(i=(unsigned)q+1;i<g_apartment.count;i++)g_apartment.item[i-1]=g_apartment.item[i];g_apartment.count--;if(apartment_save())ok=1;else g_apartment=old;}mkpkt(p,0xC410,20,1);stable_put32(p,8,ok?200u:100u);stable_resource_put16(p,18,idx);sendbuf(c,p,20);printf("  S0xC410 apartment delete success=%d code=%u index=%u len=20 t=%lds\n",ok,code,idx,sec());fflush(0);return 1;}
#endif
