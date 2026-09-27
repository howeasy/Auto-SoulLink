/* Gen 2 phone bodies rendered in the vanilla Gen 3 character set. Names are
 * already encoded and validated by call_producer; species names come from ROM. */
#ifndef SLINK_CALL_TEXT_H
#define SLINK_CALL_TEXT_H
#include "abi.h"
typedef struct { uint8_t *out;unsigned size,pos;int fits; } SlinkCallText;
static void ct_byte(SlinkCallText *t,uint8_t c)
{
    if (t->pos+1<t->size) t->out[t->pos++]=c;
    else t->fits=0;
}
static void ct_ascii(SlinkCallText *t,const char *s)
{
    while (*s) {
        unsigned c=(unsigned char)*s++;
        if (c>='A' && c<='Z') c=0xbb+c-'A';
        else if (c>='a' && c<='z') c=0xd5+c-'a';
        else if (c==' ') c=0;
        else if (c=='\n') c=0xfe;
        else if (c=='\f') c=0xfb;
        else if (c=='\v') { ct_byte(t,0xfd);c=1; } /* native PLAYER placeholder */
        else if (c=='.') c=0xad;
        else if (c=='?') c=0xac;
        else if (c=='!') c=0xab;
        else if (c==',') c=0xb8;
        else if (c=='\'') c=0xb4;
        else if (c=='-') c=0xae;
        ct_byte(t,(uint8_t)c);
    }
}
static void ct_name(SlinkCallText *t,const volatile uint8_t *s,unsigned bound)
{
    for (unsigned i=0;i<bound && s[i]!=0xff;i++) ct_byte(t,s[i]);
}
static int slink_call_text(uint8_t *out,unsigned size,const volatile SlinkCallRecordV2 *r,
                           const uint8_t *species,unsigned max_species)
{
    if (!size) return 0;
    SlinkCallText t={out,size,0,1};
    int named=r->has_names && r->caller_species && r->caller_species<=max_species
        && r->receiver_species && r->receiver_species<=max_species;
    if (named && r->event!=2) {
        ct_name(&t,r->trainer,8);ct_ascii(&t,"'s\n");
        if (r->caller_nick[0]!=0xff) ct_name(&t,r->caller_nick,11);
        else ct_name(&t,species+r->caller_species*11u,11);
        if (r->event==1) {
            ct_ascii(&t," fainted!\fYour ");ct_name(&t,species+r->receiver_species*11u,11);
            ct_ascii(&t,"\nis gone too!");
        } else {
            ct_ascii(&t,"\flinked with your\n");ct_name(&t,species+r->receiver_species*11u,11);
            ct_ascii(&t,".\fThey're linked!");
        }
    } else if (r->event==1) {
        ct_ascii(&t,"...Hello? \v?\nIt's your partner.\fOur link snapped.\nMine didn't make\fit through...\n...and yours went\fwith it. Sorry.");
    } else if (r->event==2) {
        ct_ascii(&t,"\v? Can you\nhear me? ...kssh...\fThe catch here got\naway. This place\fis a DEAD ZONE.\nDon't look back!");
    } else {
        ct_ascii(&t,"Hey, \v!\nIt's your partner!\fOur first POKEMON\nare linked. Their\fsouls are one now.\nKeep 'em alive,\fOK? Bye-bye!");
    }
    t.out[t.pos]=0xff;
    return t.fits;
}
#endif
