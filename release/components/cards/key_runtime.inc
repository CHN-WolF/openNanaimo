#ifndef NANAIMO_CARD_KEY_RUNTIME_COUNTED_KEYS_INC
#define NANAIMO_CARD_KEY_RUNTIME_COUNTED_KEYS_INC
/* COUNTED_KEYS local adapter policy.
   Static closure proves:
   - C3EA +8 is the card-guide step;
   - C3EA +9/+0A/+0B feed the three counted-key widgets;
   - C3FB carries WORD current/update guide steps and C3FC WORD +8=1 clears
     the guide controller busy latch;
   - C3ED still carries no key selector.
   Keep visible counted keys, inventory activation, and guide persistence in
   separate account ledgers. */
static unsigned g_card_key_seed[4];
static int g_card_key_seeded=0;
static int g_card_key_state_loaded=0;
static char g_card_key_state_account[48];
static unsigned g_card_key_item_count[4];
static int g_card_key_item_state_loaded=0;
static char g_card_key_item_state_account[48];
static unsigned g_card_guide_step=0u;
static int g_card_guide_state_loaded=0;
static char g_card_guide_state_account[48];

static void card_key_seed_once(void){if(g_card_key_seeded)return;g_card_key_seed[0]=g_profile_card_key_normal;g_card_key_seed[1]=g_profile_card_key_gold;g_card_key_seed[2]=g_profile_card_key_mystery;g_card_key_seed[3]=g_profile_card_key_special;g_card_key_seeded=1;}
static void card_key_state_path(char*out,const char*suffix){char a[48];unsigned n=0,i=0;const char*p="card_key_state_";card_safe_account(a);while(*p)out[n++]=*p++;while(a[i])out[n++]=a[i++];while(*suffix)out[n++]=*suffix++;out[n]=0;}
static void card_key_item_state_path(char*out,const char*suffix){char a[48];unsigned n=0,i=0;const char*p="card_key_item_state_";card_safe_account(a);while(*p)out[n++]=*p++;while(a[i])out[n++]=a[i++];while(*suffix)out[n++]=*suffix++;out[n]=0;}
static void card_guide_state_path(char*out,const char*suffix){char a[48];unsigned n=0,i=0;const char*p="card_guide_state_";card_safe_account(a);while(*p)out[n++]=*p++;while(a[i])out[n++]=a[i++];while(*suffix)out[n++]=*suffix++;out[n]=0;}
static void card_copy_account(char*out,unsigned cap,const char*a){unsigned i=0;memset(out,0,cap);while(a[i]&&i+1u<cap){out[i]=a[i];i++;}}
static void card_key_state_set_account(const char*a){card_copy_account(g_card_key_state_account,sizeof(g_card_key_state_account),a);}
static void card_key_item_state_set_account(const char*a){card_copy_account(g_card_key_item_state_account,sizeof(g_card_key_item_state_account),a);}
static void card_guide_state_set_account(const char*a){card_copy_account(g_card_guide_state_account,sizeof(g_card_guide_state_account),a);}

static void card_key_state_load(void){char account[48],path[128],bak[128],line[128];void*f;unsigned v;card_key_seed_once();card_safe_account(account);if(g_card_key_state_loaded&&card_str_eq(account,g_card_key_state_account))return;g_profile_card_key_normal=g_card_key_seed[0];g_profile_card_key_gold=g_card_key_seed[1];g_profile_card_key_mystery=g_card_key_seed[2];g_profile_card_key_special=g_card_key_seed[3];card_key_state_path(path,".dat");card_key_state_path(bak,".bak");f=fopen(path,"r");if(!f)f=fopen(bak,"r");if(f){while(fgets(line,sizeof(line),f)){if(sscanf(line,"normal=%u",&v)==1&&v<=255u)g_profile_card_key_normal=v;else if(sscanf(line,"gold=%u",&v)==1&&v<=255u)g_profile_card_key_gold=v;else if(sscanf(line,"mystery=%u",&v)==1&&v<=255u)g_profile_card_key_mystery=v;else if(sscanf(line,"special=%u",&v)==1&&v<=255u)g_profile_card_key_special=v;}fclose(f);}card_key_state_set_account(account);g_card_key_state_loaded=1;printf("  [CARD_KEY_DB] loaded account=%s normal=%u gold=%u mystery=%u special=%u source=%s\n",account,g_profile_card_key_normal,g_profile_card_key_gold,g_profile_card_key_mystery,g_profile_card_key_special,f?"file":"profile-seed");fflush(0);}
static int card_key_state_save(void){char path[128],tmp[128],bak[128];void*f;card_key_state_path(path,".dat");card_key_state_path(tmp,".new");card_key_state_path(bak,".bak");f=fopen(tmp,"w");if(!f)return 0;fprintf(f,"version=1\nnormal=%u\ngold=%u\nmystery=%u\nspecial=%u\n",g_profile_card_key_normal,g_profile_card_key_gold,g_profile_card_key_mystery,g_profile_card_key_special);if(fclose(f)!=0)return 0;remove(bak);rename(path,bak);if(rename(tmp,path)!=0){rename(bak,path);return 0;}remove(bak);return 1;}
static unsigned*card_key_count_ptr(unsigned index){if(index==0u)return &g_profile_card_key_normal;if(index==1u)return &g_profile_card_key_gold;if(index==2u)return &g_profile_card_key_mystery;if(index==3u)return &g_profile_card_key_special;return 0;}
/* Valid free entitlement first. Then consume only the three counted key types
   exposed by C3EA: normal, gold, mystery. The fourth C3E8 slot remains a
   retained legacy/account field but is not silently consumed while hidden. */
static int card_key_reserve(unsigned*kind_out,unsigned*old_count_out){unsigned i;card_key_state_load();if(g_profile_free_magic_key_expiry!=0u&&g_profile_free_magic_key_current<g_profile_free_magic_key_expiry){if(kind_out)*kind_out=4u;if(old_count_out)*old_count_out=0u;return 1;}for(i=0;i<3u;i++){unsigned*p=card_key_count_ptr(i);if(p&&*p){if(kind_out)*kind_out=i;if(old_count_out)*old_count_out=*p;(*p)--;return 1;}}return 0;}
static void card_key_restore(unsigned kind,unsigned old_count){unsigned*p;if(kind>=4u)return;p=card_key_count_ptr(kind);if(p)*p=old_count;}
static const char*card_key_kind_name(unsigned kind){if(kind==0u)return "normal";if(kind==1u)return "gold";if(kind==2u)return "mystery";if(kind==3u)return "legacy-special";if(kind==4u)return "free";return "none";}

/* C430 inventory stock is separate from the active synthesis counters. The
   initial local adapter profile seeds both ledgers for backward compatibility;
   C46D echoes the row token in C46E, removes that entire inventory row, and
   grants a fixed item-definition use count. 47000003/4 grant 10/30 mystery uses. */
static void card_key_item_state_load(void){char account[48],path[128],bak[128],line[128];void*f;unsigned v;card_key_seed_once();card_safe_account(account);if(g_card_key_item_state_loaded&&card_str_eq(account,g_card_key_item_state_account))return;g_card_key_item_count[0]=g_card_key_seed[1];g_card_key_item_count[1]=g_card_key_seed[2];g_card_key_item_count[2]=g_card_key_seed[3];g_card_key_item_count[3]=g_card_key_seed[3];card_key_item_state_path(path,".dat");card_key_item_state_path(bak,".bak");f=fopen(path,"r");if(!f)f=fopen(bak,"r");if(f){while(fgets(line,sizeof(line),f)){if(sscanf(line,"gold_item=%u",&v)==1&&v<=65535u)g_card_key_item_count[0]=v;else if(sscanf(line,"mystery_item=%u",&v)==1&&v<=65535u)g_card_key_item_count[1]=v;else if(sscanf(line,"coupon10=%u",&v)==1&&v<=65535u)g_card_key_item_count[2]=v;else if(sscanf(line,"coupon30=%u",&v)==1&&v<=65535u)g_card_key_item_count[3]=v;}fclose(f);}card_key_item_state_set_account(account);g_card_key_item_state_loaded=1;printf("  [CARD_KEY_ITEM_DB] loaded account=%s gold=%u mystery=%u coupon10=%u coupon30=%u source=%s\n",account,g_card_key_item_count[0],g_card_key_item_count[1],g_card_key_item_count[2],g_card_key_item_count[3],f?"file":"profile-seed");fflush(0);}
static int card_key_item_state_save(void){char path[128],tmp[128],bak[128];void*f;card_key_item_state_path(path,".dat");card_key_item_state_path(tmp,".new");card_key_item_state_path(bak,".bak");f=fopen(tmp,"w");if(!f)return 0;fprintf(f,"version=1\ngold_item=%u\nmystery_item=%u\ncoupon10=%u\ncoupon30=%u\n",g_card_key_item_count[0],g_card_key_item_count[1],g_card_key_item_count[2],g_card_key_item_count[3]);if(fclose(f)!=0)return 0;remove(bak);rename(path,bak);if(rename(tmp,path)!=0){rename(bak,path);return 0;}remove(bak);return 1;}
static int card_key_item_index(unsigned code){if(code==47000001u)return 0;if(code==47000002u)return 1;if(code==47000003u)return 2;if(code==47000004u)return 3;return -1;}
static unsigned card_key_item_quantity(unsigned code){int i;card_key_item_state_load();i=card_key_item_index(code);return i>=0?g_card_key_item_count[i]:0u;}
static int card_key_item_activate(unsigned code,unsigned token,unsigned*active_after,unsigned*item_after){int idx=card_key_item_index(code);unsigned target=0u,grant=1u,old_item,old_active;unsigned*p=0;int key_saved=0,item_saved=0;if(active_after)*active_after=0;if(item_after)*item_after=0;if(idx<0||token==0u)return 0;card_key_state_load();card_key_item_state_load();if(token!=g_card_key_item_count[idx])return 0;if(code==47000001u){target=1u;grant=1u;}else if(code==47000002u){target=2u;grant=1u;}else if(code==47000003u){target=2u;grant=10u;}else{target=2u;grant=30u;}p=card_key_count_ptr(target);if(!p||*p>255u-grant)return 0;old_item=g_card_key_item_count[idx];old_active=*p;g_card_key_item_count[idx]=0u;*p+=grant;key_saved=card_key_state_save();if(key_saved)item_saved=card_key_item_state_save();if(key_saved&&item_saved){if(active_after)*active_after=*p;if(item_after)*item_after=0u;printf("  [CARD_KEY_ACTIVATE] commit code=%u token=%u grant=%u target=%s active=%u item=0\n",code,token,grant,card_key_kind_name(target),*p);fflush(0);return 1;}g_card_key_item_count[idx]=old_item;*p=old_active;card_key_state_save();card_key_item_state_save();printf("  [CARD_KEY_ACTIVATE] rollback code=%u token=%u key_saved=%d item_saved=%d\n",code,token,key_saved,item_saved);fflush(0);return 0;}

static void card_guide_state_load(void){char account[48],path[128],bak[128],line[128];void*f;unsigned v,seed=0u;card_safe_account(account);if(g_card_guide_state_loaded&&card_str_eq(account,g_card_guide_state_account))return;
#if TEAMPLAY_FEATURE_SKIP_TUTORIAL
seed=g_skip_tutorial?3u:0u;
#endif
g_card_guide_step=seed;card_guide_state_path(path,".dat");card_guide_state_path(bak,".bak");f=fopen(path,"r");if(!f)f=fopen(bak,"r");if(f){while(fgets(line,sizeof(line),f))if(sscanf(line,"step=%u",&v)==1&&v<=4u)g_card_guide_step=v;fclose(f);}card_guide_state_set_account(account);g_card_guide_state_loaded=1;printf("  [CARD_GUIDE_DB] loaded account=%s step=%u source=%s\n",account,g_card_guide_step,f?"file":"profile-seed");fflush(0);}
static int card_guide_state_save(void){char path[128],tmp[128],bak[128];void*f;card_guide_state_path(path,".dat");card_guide_state_path(tmp,".new");card_guide_state_path(bak,".bak");f=fopen(tmp,"w");if(!f)return 0;fprintf(f,"version=1\nstep=%u\n",g_card_guide_step);if(fclose(f)!=0)return 0;remove(bak);rename(path,bak);if(rename(tmp,path)!=0){rename(bak,path);return 0;}remove(bak);return 1;}
static unsigned card_guide_step_current(void){card_guide_state_load();return g_card_guide_step;}
static int card_guide_step_update(unsigned now,unsigned update){unsigned old;card_guide_state_load();if(now>4u||update>4u||update<now)return 0;if(update<=g_card_guide_step)return 1;old=g_card_guide_step;g_card_guide_step=update;if(card_guide_state_save()){printf("  [CARD_GUIDE] commit now=%u update=%u persisted=%u\n",now,update,g_card_guide_step);fflush(0);return 1;}g_card_guide_step=old;card_guide_state_save();printf("  [CARD_GUIDE] rollback now=%u update=%u restored=%u\n",now,update,g_card_guide_step);fflush(0);return 0;}
#endif