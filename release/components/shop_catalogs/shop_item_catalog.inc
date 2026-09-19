#ifndef NANAIMO_SHOP_CATALOGS_SHOP_ITEM_CATALOG_INC
#define NANAIMO_SHOP_CATALOGS_SHOP_ITEM_CATALOG_INC
/* Generated from statically closed resource price columns. carrier1=C430, carrier2=C474. */
struct shop_purchase_shop_item_row { unsigned code,price; unsigned char carrier; };
#define SHOP_PURCHASE_SHOP_ITEM_COUNT 35u
static const struct shop_purchase_shop_item_row shop_purchase_shop_items[SHOP_PURCHASE_SHOP_ITEM_COUNT]={
    {14002486u,16u,1u},
    {14002487u,30u,1u},
    {18000001u,480u,1u},
    {18000002u,200u,1u},
    {42000001u,40u,2u},
    {42000002u,248u,2u},
    {42000006u,240u,2u},
    {42000007u,600u,2u},
    {42000008u,450u,2u},
    {43000002u,880u,2u},
    {43000003u,1250u,2u},
    {43100002u,110u,2u},
    {44000001u,60u,2u},
    {44000003u,80u,2u},
    {44000004u,60u,2u},
    {44000009u,20u,2u},
    {44000010u,140u,2u},
    {44000011u,288u,2u},
    {44000012u,150u,2u},
    {44000013u,288u,2u},
    {44000014u,45u,2u},
    {44000015u,180u,2u},
    {44000016u,300u,2u},
    {44000017u,50u,2u},
    {44000018u,150u,2u},
    {44000019u,180u,2u},
    {44000020u,180u,2u},
    {44000021u,150u,2u},
    {45000001u,288u,2u},
    {45000002u,288u,2u},
    {45000003u,3600u,2u},
    {48000001u,70u,2u},
    {48000004u,15u,2u},
    {48000006u,150u,2u},
    {48000007u,360u,2u},
};
static const struct shop_purchase_shop_item_row*shop_purchase_shop_item_find(unsigned code){int lo=0,hi=(int)SHOP_PURCHASE_SHOP_ITEM_COUNT-1;while(lo<=hi){int m=(lo+hi)/2;unsigned c=shop_purchase_shop_items[m].code;if(c==code)return &shop_purchase_shop_items[m];if(c<code)lo=m+1;else hi=m-1;}return 0;}
#endif
