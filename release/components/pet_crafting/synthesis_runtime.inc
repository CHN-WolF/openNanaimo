#ifndef NANAIMO_CARD_SYNTHESIS_RUNTIME_ITEM_EFFECTS_INC
#define NANAIMO_CARD_SYNTHESIS_RUNTIME_ITEM_EFFECTS_INC
#include "../cards/synthesis_recipe_data.inc"
#include "../cards/key_runtime.inc"
#define CARD_SYNTH_VISIBLE_ITEM_MAX 65535u
#define CARD_SYNTH_ITEM_CAP 1024u
struct card_synth_item_row { unsigned code,count; };
static struct card_synth_item_row g_card_synth_items[CARD_SYNTH_ITEM_CAP];
static unsigned g_card_synth_item_n=0u;
static int g_card_synth_items_loaded=0;
static char g_card_synth_items_account[32];
static const struct card_synthesis_recipe*card_synthesis_find(unsigned token){int lo=0,hi=(int)CARD_SYNTHESIS_RECIPE_COUNT-1;while(lo<=hi){int m=(lo+hi)/2;unsigned t=g_card_synthesis_recipes[m].token;if(t==token)return &g_card_synthesis_recipes[m];if(t<token)lo=m+1;else hi=m-1;}return 0;}
static void card_synth_item_path(char*out,const char*suffix){char a[32];unsigned n=0,i=0;const char*p="card_synthesis_rewards_";card_safe_account(a);while(*p)out[n++]=*p++;while(a[i])out[n++]=a[i++];while(*suffix)out[n++]=*suffix++;out[n]=0;}
static void card_synth_items_load(void){char account[32],path[128],bak[128],line[128];void*f;unsigned code,count;card_safe_account(account);if(g_card_synth_items_loaded&&card_str_eq(account,g_card_synth_items_account))return;g_card_synth_item_n=0u;memset(g_card_synth_items,0,sizeof(g_card_synth_items));card_synth_item_path(path,".dat");card_synth_item_path(bak,".bak");f=fopen(path,"r");if(!f)f=fopen(bak,"r");if(f){while(fgets(line,sizeof(line),f)){if(sscanf(line,"%u=%u",&code,&count)==2&&count&&g_card_synth_item_n<CARD_SYNTH_ITEM_CAP){g_card_synth_items[g_card_synth_item_n].code=code;g_card_synth_items[g_card_synth_item_n].count=count;g_card_synth_item_n++;}}fclose(f);}memset(g_card_synth_items_account,0,sizeof(g_card_synth_items_account));{unsigned i=0;while(account[i]&&i+1u<sizeof(g_card_synth_items_account)){g_card_synth_items_account[i]=account[i];i++;}}g_card_synth_items_loaded=1;printf("  [CARD_SYNTH_DB] loaded account=%s item_kinds=%u\n",account,g_card_synth_item_n);fflush(0);}
static int card_synth_items_save(void){char path[128],tmp[128],bak[128];void*f;unsigned i;card_synth_item_path(path,".dat");card_synth_item_path(tmp,".new");card_synth_item_path(bak,".bak");f=fopen(tmp,"w");if(!f)return 0;fprintf(f,"version=1\n");for(i=0;i<g_card_synth_item_n;i++)if(g_card_synth_items[i].code&&g_card_synth_items[i].count)fprintf(f,"%u=%u\n",g_card_synth_items[i].code,g_card_synth_items[i].count);if(fclose(f)!=0)return 0;remove(bak);rename(path,bak);if(rename(tmp,path)!=0){rename(bak,path);return 0;}remove(bak);return 1;}
static int card_synth_item_index(unsigned code){unsigned i;for(i=0;i<g_card_synth_item_n;i++)if(g_card_synth_items[i].code==code)return (int)i;return -1;}
static int card_synth_materials(const struct card_synthesis_recipe*r,unsigned codes[3],unsigned need[3],unsigned*unique_n){unsigned in[3],i,j,n=0;in[0]=r->in0;in[1]=r->in1;in[2]=r->in2;for(i=0;i<3u;i++){if(!in[i])continue;for(j=0;j<n;j++)if(codes[j]==in[i])break;if(j<n)need[j]++;else{codes[n]=in[i];need[n]=1u;n++;}}*unique_n=n;return n>0u;}
/* ITEM_EFFECTS correction: domain21 is the flying-game-item family and is persisted
   in the ordinary synthesis-item ledger. The old domain21-as-SP policy is retracted.
   Local adapter key selection remains request-side policy. Key selection is the
   explicit adapter-side policy in key_runtime.inc because C3ED +0x0A is
   uninitialized padding at all three active card submit callsites. */
static int card_synthesis_commit(unsigned token,unsigned*output_out,unsigned*kind_out,unsigned*amount_out){
 const struct card_synthesis_recipe*r=card_synthesis_find(token);unsigned codes[3]={0,0,0},need[3]={0,0,0},old_counts[3]={0,0,0},n=0,i,domain,output,kind=0,amount=0;unsigned old_pet_n=0,old_sp=0,item_idx=0,old_item_n=0,old_item_count=0,key_kind=99u,key_old_count=0u;int reward_saved=0,card_saved=0,key_saved=0,rollback_ok=1;
 if(output_out)*output_out=0;if(kind_out)*kind_out=0;if(amount_out)*amount_out=0;
 if(!r){printf("  [CARD_SYNTH] reject token=%u reason=unknown-token\n",token);fflush(0);return 0;}
 card_db_load();card_synth_items_load();skill_progress_load();card_key_state_load();output=r->output;domain=output/1000000u;
 if(!card_synth_materials(r,codes,need,&n)){printf("  [CARD_SYNTH] reject token=%u reason=no-material-definition\n",token);fflush(0);return 0;}
 for(i=0;i<n;i++){int idx=card_code_index(codes[i]);if(idx<0||g_card_counts[idx]<need[i]){printf("  [CARD_SYNTH] reject token=%u reason=material material=%u need=%u have=%u\n",token,codes[i],need[i],idx>=0?g_card_counts[idx]:0u);fflush(0);return 0;}old_counts[i]=g_card_counts[idx];}
 if(domain==15u){unsigned price,a,b;if(!shopping_pet_lookup(output,&price,&a,&b)||shopping_find(g_owned_pets,g_owned_pets_n,output)>=0||g_owned_pets_n>=SHOPPING_MAX_OWNED_PETS){printf("  [CARD_SYNTH] reject token=%u reason=pet-reward output=%u\n",token,output);fflush(0);return 0;}old_pet_n=g_owned_pets_n;kind=2u;amount=1u;}
 else if(domain==14u||domain==17u||domain==18u||domain==19u||domain==21u||domain==41u){int q=card_synth_item_index(output);old_item_n=g_card_synth_item_n;if(q<0){if(g_card_synth_item_n>=CARD_SYNTH_ITEM_CAP){printf("  [CARD_SYNTH] reject token=%u reason=item-cap\n",token);fflush(0);return 0;}item_idx=g_card_synth_item_n++;g_card_synth_items[item_idx].code=output;g_card_synth_items[item_idx].count=0u;}else item_idx=(unsigned)q;old_item_count=g_card_synth_items[item_idx].count;if(old_item_count>=CARD_SYNTH_VISIBLE_ITEM_MAX){g_card_synth_item_n=old_item_n;printf("  [CARD_SYNTH] reject token=%u reason=item-visible-u16-cap count=%u\n",token,old_item_count);fflush(0);return 0;}kind=1u;amount=1u;}
 else{printf("  [CARD_SYNTH] reject token=%u reason=unsupported-reward output=%u\n",token,output);fflush(0);return 0;}
 if(!card_key_reserve(&key_kind,&key_old_count)){if(kind==1u)g_card_synth_item_n=old_item_n;printf("  [CARD_SYNTH] reject token=%u reason=missing-key\n",token);fflush(0);return 0;}
 for(i=0;i<n;i++)g_card_counts[card_code_index(codes[i])]-=need[i];
 if(kind==2u){g_owned_pets[g_owned_pets_n++]=output;reward_saved=shopping_state_save();}
 else if(kind==3u){g_skill_progress_sp+=amount;reward_saved=skill_progress_save();}
 else{g_card_synth_items[item_idx].count++;reward_saved=card_synth_items_save();}
 if(reward_saved)card_saved=card_db_save();
 if(reward_saved&&card_saved){if(key_kind==4u)key_saved=1;else key_saved=card_key_state_save();}
 if(reward_saved&&card_saved&&key_saved){if(output_out)*output_out=output;if(kind_out)*kind_out=kind;if(amount_out)*amount_out=amount;printf("  [CARD_SYNTH] commit token=%u inputs=%u/%u/%u output=%u kind=%u amount=%u key=%s remaining=%u\n",token,r->in0,r->in1,r->in2,output,kind,amount,card_key_kind_name(key_kind),key_kind<4u?*card_key_count_ptr(key_kind):0u);fflush(0);return 1;}
 for(i=0;i<n;i++)g_card_counts[card_code_index(codes[i])]=old_counts[i];card_key_restore(key_kind,key_old_count);
 if(kind==2u){g_owned_pets_n=old_pet_n;if(!shopping_state_save())rollback_ok=0;}
 else if(kind==3u){g_skill_progress_sp=old_sp;if(!skill_progress_save())rollback_ok=0;}
 else{g_card_synth_item_n=old_item_n;if(item_idx<old_item_n)g_card_synth_items[item_idx].count=old_item_count;if(!card_synth_items_save())rollback_ok=0;}
 if(!card_db_save())rollback_ok=0;if(key_kind<4u&&!card_key_state_save())rollback_ok=0;
 printf("  [CARD_SYNTH] rollback token=%u reward_saved=%d card_saved=%d key_saved=%d rollback_ok=%d\n",token,reward_saved,card_saved,key_saved,rollback_ok);fflush(0);return 0;
}
static void send_c3ea_card_synthesis_entry(SOCKET c){char p[4096];unsigned guide;card_key_state_load();guide=card_guide_step_current();mkpkt(p,0xC3EA,20,1);p[8]=(char)guide;p[9]=(char)g_profile_card_key_normal;p[10]=(char)g_profile_card_key_gold;p[11]=(char)g_profile_card_key_mystery;stable_put32(p,12,g_profile_free_magic_key_expiry);stable_put32(p,16,g_profile_free_magic_key_current);sendbuf(c,p,20);printf("  S0xC3EA CARD_ITEM_QUANTITY guide=%u normal=%u gold=%u mystery=%u free_expiry=%u free_current=%u len=20 t=%lds\n",guide,g_profile_card_key_normal,g_profile_card_key_gold,g_profile_card_key_mystery,g_profile_free_magic_key_expiry,g_profile_free_magic_key_current,sec());fflush(0);}
static void send_c3fc_card_guide_result(SOCKET c,int success){char p[4096];mkpkt(p,0xC3FC,10,1);p[8]=(char)(success?1:0);p[9]=0;sendbuf(c,p,10);printf("  S0xC3FC CARD_ITEM_QUANTITY guide update success=%d status=%u len=10 t=%lds\n",success,success?1u:0u,sec());fflush(0);}
static void send_c3ee_card_synthesis_result(SOCKET c,int success,unsigned output){char p[4096];mkpkt(p,0xC3EE,16,1);stable_put32(p,8,success?400u:0u);stable_put32(p,12,success?output:0u);sendbuf(c,p,16);printf("  S0xC3EE CARD_ITEM_QUANTITY card-synthesis success=%d ans=%u output=%u len=16 t=%lds\n",success,success?400u:0u,success?output:0u,sec());fflush(0);}
static void send_c3f0_card_synthesis_finish(SOCKET c){char p[4096];mkpkt(p,0xC3F0,12,1);stable_put32(p,8,10u);sendbuf(c,p,12);printf("  S0xC3F0 compatibility finish code=10 len=12 t=%lds\n",sec());fflush(0);}
#endif
