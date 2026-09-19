#ifndef NANAIMO_MAP_IDENTITY_RUNTIME_INC
#define NANAIMO_MAP_IDENTITY_RUNTIME_INC

/* Generic shooting-resource identity.  The tuple names follow the shipped
   hd%d_ep%02d_dg%02d_st%02d.sstg namespace.  CF77 carries the base tuple
   (hd/episode/dungeon/difficulty); CF6C additionally carries stage_index.
   absolute_slot is the resource-table flattening difficulty*3+stage_index. */
#define MAP_IDENTITY_HAVE_HD          0x01u
#define MAP_IDENTITY_HAVE_EPISODE     0x02u
#define MAP_IDENTITY_HAVE_DUNGEON     0x04u
#define MAP_IDENTITY_HAVE_STAGE       0x08u
#define MAP_IDENTITY_HAVE_DIFFICULTY  0x10u
#define MAP_IDENTITY_HAVE_BASE (MAP_IDENTITY_HAVE_HD|MAP_IDENTITY_HAVE_EPISODE|MAP_IDENTITY_HAVE_DUNGEON|MAP_IDENTITY_HAVE_DIFFICULTY)
#define MAP_IDENTITY_HAVE_FULL (MAP_IDENTITY_HAVE_BASE|MAP_IDENTITY_HAVE_STAGE)
#define MAP_IDENTITY_SOURCE_CF77 0x01u
#define MAP_IDENTITY_SOURCE_CF6C 0x02u
#define MAP_IDENTITY_SOURCE_CFEB 0x04u
#define MAP_IDENTITY_SOURCE_CF8B 0x08u
#define MAP_IDENTITY_MAX_DIFFICULTY 2u
#define MAP_IDENTITY_STAGES_PER_DIFFICULTY 3u
#define MAP_IDENTITY_MAX_STAGE_INDEX 2u

typedef struct map_identity_runtime {
    unsigned hd,episode,dungeon,stage_index,difficulty,absolute_slot;
    unsigned valid_mask,source_mask;
    unsigned transport_epoch,room_epoch,battle_epoch,generation;
    unsigned conflict_count,rejected_count;
    unsigned cf6c_authoritative;
    unsigned blocked;
} map_identity_runtime;

static void map_identity_zero_tuple(map_identity_runtime*m){m->hd=0u;m->episode=0u;m->dungeon=0u;m->stage_index=0u;m->difficulty=0u;m->absolute_slot=0u;m->valid_mask=0u;m->source_mask=0u;m->cf6c_authoritative=0u;m->blocked=0u;}
static void map_identity_init(map_identity_runtime*m){memset(m,0,sizeof(*m));}
static void map_identity_reset_transport(map_identity_runtime*m){unsigned next=m->transport_epoch+1u;unsigned conflicts=m->conflict_count,rejected=m->rejected_count;map_identity_zero_tuple(m);m->transport_epoch=next?next:1u;m->room_epoch=0u;m->battle_epoch=0u;m->generation++;m->conflict_count=conflicts;m->rejected_count=rejected;}
static void map_identity_reset_room(map_identity_runtime*m){map_identity_zero_tuple(m);m->room_epoch++;if(!m->room_epoch)m->room_epoch=1u;m->battle_epoch=0u;m->generation++;}
static int map_identity_values_valid(unsigned difficulty,unsigned stage_index,int have_stage){if(difficulty>MAP_IDENTITY_MAX_DIFFICULTY)return 0;if(have_stage&&stage_index>MAP_IDENTITY_MAX_STAGE_INDEX)return 0;return 1;}
static void map_identity_recompute_slot(map_identity_runtime*m){if((m->valid_mask&MAP_IDENTITY_HAVE_FULL)==MAP_IDENTITY_HAVE_FULL)m->absolute_slot=m->difficulty*MAP_IDENTITY_STAGES_PER_DIFFICULTY+m->stage_index;else m->absolute_slot=0u;}
static int map_identity_base_equal(const map_identity_runtime*m,unsigned hd,unsigned ep,unsigned dg,unsigned diff){return (m->valid_mask&MAP_IDENTITY_HAVE_BASE)==MAP_IDENTITY_HAVE_BASE&&m->hd==hd&&m->episode==ep&&m->dungeon==dg&&m->difficulty==diff;}
/* CF77 is a base-resource hint.  It may seed a flow that omits CF6C, but it
   cannot override an authoritative CF6C tuple.  Conflicting hint-only tuples
   fail closed until CF6C or a new room/transport epoch. */
static int map_identity_apply_cf77(map_identity_runtime*m,unsigned hd,unsigned ep,unsigned dg,unsigned diff){
    if(!map_identity_values_valid(diff,0u,0)){m->rejected_count++;return 0;}
    if(m->cf6c_authoritative){if(!map_identity_base_equal(m,hd,ep,dg,diff))m->conflict_count++;return map_identity_base_equal(m,hd,ep,dg,diff);}
    if((m->valid_mask&MAP_IDENTITY_HAVE_BASE)==MAP_IDENTITY_HAVE_BASE&&!map_identity_base_equal(m,hd,ep,dg,diff)){m->conflict_count++;m->blocked=1u;return 0;}
    m->hd=hd;m->episode=ep;m->dungeon=dg;m->difficulty=diff;m->valid_mask|=MAP_IDENTITY_HAVE_BASE;m->source_mask|=MAP_IDENTITY_SOURCE_CF77;m->generation++;map_identity_recompute_slot(m);return 1;
}
/* CF6C starts/re-identifies the room and is authoritative over an earlier
   CF77 hint.  A valid CF6C tuple clears hint conflict blocking. */
static int map_identity_apply_cf6c(map_identity_runtime*m,unsigned hd,unsigned ep,unsigned dg,unsigned st,unsigned diff){
    if(!map_identity_values_valid(diff,st,1)){m->rejected_count++;m->blocked=1u;return 0;}
    if((m->valid_mask&MAP_IDENTITY_HAVE_BASE)==MAP_IDENTITY_HAVE_BASE&&!map_identity_base_equal(m,hd,ep,dg,diff))m->conflict_count++;
    m->hd=hd;m->episode=ep;m->dungeon=dg;m->stage_index=st;m->difficulty=diff;m->valid_mask=MAP_IDENTITY_HAVE_FULL;m->source_mask|=MAP_IDENTITY_SOURCE_CF6C;m->cf6c_authoritative=1u;m->blocked=0u;m->generation++;map_identity_recompute_slot(m);return 1;
}
static int map_identity_apply_stage(map_identity_runtime*m,unsigned st,unsigned source){if(st>MAP_IDENTITY_MAX_STAGE_INDEX||(m->valid_mask&MAP_IDENTITY_HAVE_BASE)!=MAP_IDENTITY_HAVE_BASE){m->rejected_count++;m->blocked=1u;return 0;}m->stage_index=st;m->valid_mask|=MAP_IDENTITY_HAVE_STAGE;m->source_mask|=source;m->blocked=0u;m->generation++;map_identity_recompute_slot(m);return 1;}
static int map_identity_apply_cfeb(map_identity_runtime*m,unsigned real_stage){return map_identity_apply_stage(m,real_stage,MAP_IDENTITY_SOURCE_CFEB);}
static int map_identity_apply_cf8b(map_identity_runtime*m,unsigned effective_stage){return map_identity_apply_stage(m,effective_stage,MAP_IDENTITY_SOURCE_CF8B);}
static int map_identity_combat_ready(const map_identity_runtime*m){return !m->blocked&&(m->valid_mask&MAP_IDENTITY_HAVE_FULL)==MAP_IDENTITY_HAVE_FULL&&m->difficulty<=MAP_IDENTITY_MAX_DIFFICULTY&&m->stage_index<=MAP_IDENTITY_MAX_STAGE_INDEX;}
static void map_identity_begin_battle(map_identity_runtime*m,unsigned battle_epoch){m->battle_epoch=battle_epoch;}

#endif
