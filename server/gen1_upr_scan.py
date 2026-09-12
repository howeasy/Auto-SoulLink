"""Exhaustive RBY candidate audit against a hash-pinned clean user ROM.

Immutable pointer roots are walked from the canonical image. Repacked evolution
roots are instead bounded, semantically checked and reserialized independently.
Every changed byte must then belong to an explicitly validated domain.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path

from server.adapters.gen1_rom_scan import scan_evos_moves, scan_pokedex_order
from server.rom_change_audit import RomAuditError, RomChangeAudit

ROOT=Path(__file__).resolve().parents[1]
LAYOUT=json.loads((ROOT/"data/games/gen1_rby/upr_layout.json").read_text())
LOCK=json.loads((ROOT/"data/pret_sources.lock.json").read_text())
TITLES={"red":"pokered","blue":"pokeblue","yellow":"pokeyellow"}


def _pointer(rom, offset, bank):
    if not 0<=offset<=len(rom)-2:raise RomAuditError("pointer root outside ROM")
    pointer=int.from_bytes(rom[offset:offset+2],"little")
    if not 0x4000<=pointer<0x8000:raise RomAuditError(f"pointer outside bank window at {offset:#x}")
    return bank*0x4000+pointer-0x4000


class _Scanner:
    def __init__(self, original, candidate):
        digest=hashlib.sha1(original).hexdigest()
        self.variant=next((variant for variant,title in TITLES.items() if LOCK["clean_roms"][title]["sha1"]==digest),None)
        if self.variant is None:raise RomAuditError("canonical clean R/B/Y source required")
        self.audit=RomChangeAudit(original,candidate)
        self.original,self.candidate=original,candidate
        self.layout=LAYOUT["profiles"][self.variant]
        self.cfg=self.layout["settings"]
        self.dex=scan_pokedex_order(original)
        if len(self.dex)!=151 or set(self.dex.values())!=set(range(1,152)):
            raise RomAuditError("canonical species inventory differs")
        self.reverse={value:key for key,value in self.dex.items()}
        self.species=set(self.dex)
        self.profile={"variant":self.variant}

    def wild(self):
        raw=self.original;cfg=self.cfg;audit=self.audit
        root=cfg["WildPokemonTableOffset"];bank=root//0x4000
        first=_pointer(raw,root,bank)
        count=(first-root)//2-1
        if count!=(249 if self.variant=="yellow" else 248) or raw[root+count*2:first]!=b"\xff\xff":
            raise RomAuditError("wild pointer count/terminator differs")
        seen=set();slots=[]
        for index in range(count):
            offset=_pointer(raw,root+2*index,bank)
            if offset in seen:continue
            seen.add(offset)
            for _ in range(2):
                rate=raw[offset];offset+=1
                if rate:
                    for slot in range(10):slots.append(offset+slot*2+1)
                    offset+=20
        slots.extend([cfg["OldRodOffset"]+1,cfg["GoodRodOffset"]+1,cfg["GoodRodOffset"]+3])
        cursor=cfg["SuperRodTableOffset"];bank=cursor//0x4000;seen=set()
        for _ in range(256):
            if raw[cursor]==255:break
            if self.variant=="yellow":
                slots.extend(cursor+1+2*slot for slot in range(4));cursor+=9
            else:
                offset=_pointer(raw,cursor+1,bank);cursor+=3
                if offset not in seen:
                    seen.add(offset)
                    count=raw[offset]
                    if not 1<=count<=4:raise RomAuditError("Super Rod group count differs")
                    slots.extend(offset+2+2*slot for slot in range(count))
        else:raise RomAuditError("Super Rod terminator absent")
        self.profile["wild_species"]=[audit.value(offset,self.species,"wild species") for offset in sorted(set(slots))]

    def statics(self):
        result=[]
        for record in self.layout["statics"]:
            if record["ghost"]:continue  # all ghost bytes remain protected
            offsets=record["Species"]
            species=self.audit.value(offsets[0],self.species,"grant/static species")
            for offset in offsets[1:]:self.audit.expect(offset,bytes([species]),"grant/static species")
            result.append({"species":species,"level":self.original[record["Level"][0]]})
        self.profile["statics"]=result

    def trainers(self):
        raw=self.original;root=self.cfg["TrainerDataTableOffset"];bank=root//0x4000
        counts=self.cfg["TrainerDataClassCounts"]
        if len(counts)!=48 or counts[0]!=0:raise RomAuditError("trainer class counts differ")
        records=[];used=set()
        for group in range(1,48):
            cursor=_pointer(raw,root+2*(group-1),bank)
            for index in range(counts[group]):
                if cursor in used:raise RomAuditError("trainer record aliases another record")
                used.add(cursor);special=raw[cursor]==255
                level=None if special else self.audit.value(cursor,range(1,101),"trainer levels")
                cursor+=1;party=[]
                for _ in range(7):
                    if raw[cursor]==0:cursor+=1;break
                    if len(party)==6:raise RomAuditError("trainer party exceeds six members")
                    if special:
                        level=self.audit.value(cursor,range(1,101),"trainer levels");cursor+=1
                    label="Yellow rival starter/trainer species" if self.variant=="yellow" and cursor==self.cfg["StarterOffsets2"][0] else "trainer species"
                    species=self.audit.value(cursor,self.species,label);cursor+=1
                    party.append([level,species])
                if not party:raise RomAuditError("trainer party is empty")
                records.append({"class":group,"index":index,"party":party})
        self.profile["trainers"]=records

    def evolutions(self):
        cfg=self.cfg;audit=self.audit;raw=self.original;candidate=self.candidate
        root=cfg["PokemonMovesetsTableOffset"];count=cfg["InternalPokemonCount"]
        if count!=190:raise RomAuditError("internal species count differs")
        start=root+count*2;size=cfg["PokemonMovesetsDataSize"]
        extra=cfg["PokemonMovesetsExtraSpaceOffset"]
        regions=[(start,start+size)]
        if extra:regions.append((extra,(extra//0x4000+1)*0x4000))
        canonical=scan_evos_moves(raw);logical={};serialized={}
        stones={row[1] for mon in canonical.values() for row in mon["evolutions"] if row[0]=="item"}
        def read(offset,n):
            if not any(low<=offset and offset+n<=high for low,high in regions):
                raise RomAuditError("evolution/moves record leaves its declared data regions")
            return candidate[offset:offset+n]
        for species in sorted(self.species):
            cursor=_pointer(candidate,root+(species-1)*2,root//0x4000)
            begin=cursor;evos=[];moves=[]
            for _ in range(9):
                method=read(cursor,1)[0]
                if method==0:cursor+=1;break
                if len(evos)==8:raise RomAuditError("evolution terminator absent")
                if method not in (1,2,3):raise RomAuditError("invalid evolution method")
                row=read(cursor,4 if method==2 else 3);cursor+=len(row)
                parameter=row[1];target=row[-1]
                if target not in self.species:raise RomAuditError("invalid evolution target")
                if method==1 and not 1<=parameter<=100:raise RomAuditError("invalid evolution level")
                if method==2 and (parameter not in stones or row[2]!=1):raise RomAuditError("invalid evolution stone/minimum level")
                if method==3 and parameter!=1:raise RomAuditError("invalid trade evolution minimum level")
                evos.append(({1:"level",2:"item",3:"trade"}[method],parameter,target))
            for _ in range(65):
                level=read(cursor,1)[0]
                if level==0:cursor+=1;break
                if len(moves)==64:raise RomAuditError("learnset terminator absent")
                row=read(cursor,2);cursor+=2
                if not 1<=level<=100 or not 1<=row[1]<=165:raise RomAuditError("invalid learnset level/move")
                moves.append(tuple(row))
            original=canonical[species]
            if [row[2] for row in evos]!=[row[2] for row in original["evolutions"]]:
                raise RomAuditError("evolution targets/families changed")
            if moves!=original["moves"]:raise RomAuditError("level-up learnset changed")
            logical[species]={"evolutions":evos,"moves":moves}
            serialized[species]=candidate[begin:cursor]
        # Exact UPR serialization: zero-filled data blocks, shared leading zero,
        # and one shared null entry. This validates aliases, unused pointers and
        # unused bytes instead of exempting an entire writable bank.
        if any(candidate[low:high]!=raw[low:high] for low,high in [(root,start),*regions]):
            blocks=[bytearray(high-low) for low,high in regions];used=[0]*len(blocks)
            pointers=bytearray(count*2);null=None
            for species in range(1,count+1):
                if species not in self.species and null is not None:
                    target=null
                else:
                    record=serialized.get(species,b"\0\0")
                    for index,block in enumerate(blocks):
                        share=used[index]>0 and record[0]==0
                        needed=len(record)-int(share)
                        if used[index]+needed<=len(block):
                            target=regions[index][0]+used[index]-int(share)
                            block[used[index]:used[index]+needed]=record[int(share):]
                            used[index]+=needed
                            break
                    else:raise RomAuditError("evolution serialization capacity exceeded")
                    if species not in self.species:null=target
                pointer=target%0x4000+0x4000
                pointers[(species-1)*2:species*2]=pointer.to_bytes(2,"little")
            audit.expect(root,bytes(pointers),"evolution/moves repacking")
            for (low,_),block in zip(regions,blocks):audit.expect(low,bytes(block),"evolution/moves repacking")
        self.profile["evolution_moves"]={str(key):value for key,value in logical.items()}

    def _text(self, offset, maximum):
        table={value:key for key,value in LAYOUT["text_encoding"].items()}
        result=[]
        for value in self.audit.read(offset,maximum,original=True):
            if value==0x50:break
            result.append(table.get(value,f"\\x{value:02X}"))
        return "".join(result)

    def _encoded(self,text):
        table=LAYOUT["text_encoding"];tokens=sorted(table,key=len,reverse=True);output=[]
        while text:
            if text.startswith("\\x"):
                output.append(int(text[2:4],16));text=text[4:];continue
            token=next((token for token in tokens if text.startswith(token)),None)
            if token is None:raise RomAuditError("unsupported text token in checked template")
            output.append(table[token]);text=text[len(token):]
        return bytes(output)

    def _optional(self,spans,label):
        if any(self.audit.read(offset,len(data))!=self.audit.read(offset,len(data),original=True) for offset,data in spans):
            for offset,data in spans:self.audit.expect(offset,data,label)

    def starters(self):
        cfg=self.cfg;starters=[]
        for index in range(1,3 if self.variant=="yellow" else 4):
            offsets=cfg[f"StarterOffsets{index}"]
            label="Yellow rival starter/trainer species" if self.variant=="yellow" and index==2 else "starter species"
            species=self.audit.value(offsets[0],self.species,label)
            for offset in offsets[1:]:self.audit.expect(offset,bytes([species]),"starter species")
            starters.append(species)
        self.profile["starters"]=starters
        if self.variant=="yellow":
            if self.dex[starters[0]]!=25:
                self._optional([(cfg["PikachuHappinessCheckOffset"],b"\0\0")],"Yellow randomized starter gift access")
            return
        for species,record in zip(starters,self.layout["starter_text_bounds"]):
            offset=record["offset"]
            name=self._text(cfg["PokemonNamesOffset"]+(species-1)*cfg["PokemonNamesLength"],cfg["PokemonNamesLength"])
            encoded=self._encoded("So! You want\\n"+name+"?\\e")
            if offset+len(encoded)>record["limit"]:raise RomAuditError("starter text exceeds its source allocation")
            self._optional([(offset,encoded)],"starter descriptive text")
        values={}
        for species in starters:
            dex=self.dex[species]-1;ram=cfg["PokedexRamOffset"]+dex//8
            values[ram]=values.get(ram,0)|(1<<(dex%8))
        start=cfg["StarterPokedexBranchOffset"];off_start=start+len(values)*5+3
        pointer=lambda address:(address%0x4000+0x4000).to_bytes(2,"little")
        on=bytearray();off=bytearray([0xaf])
        for ram,value in sorted(values.items()):
            on.extend(bytes([0x3e,value,0xea])+ram.to_bytes(2,"little"))
            off.extend(bytes([0xea])+ram.to_bytes(2,"little"))
        on.extend(b"\xc3"+pointer(cfg["StarterPokedexOnOffset"]+5))
        off.extend(b"\xc3"+pointer(cfg["StarterPokedexOffOffset"]+4))
        self._optional([(cfg["StarterPokedexOnOffset"],b"\xc3"+pointer(start)+b"\0\0"),
                        (cfg["StarterPokedexOffOffset"],b"\xc3"+pointer(off_start)+b"\0"),
                        (start,bytes(on+off))],"starter Pokédex preview serialization")

    def tms(self):
        cfg=self.cfg;root=cfg["TMMovesOffset"]
        moves=[self.audit.value(root+index,range(1,166),"TM assignment") for index in range(50)]
        names={};cursor=cfg["MoveNamesOffset"]
        for move in range(1,166):
            end=self.original.index(b"\x50",cursor,cursor+32)
            names[move]=self._text(cursor,end-cursor)
            cursor=end+1
        for record in self.layout["tm_text"]:
            text=record["template"].replace("%m",names[moves[record["number"]-1]])
            encoded=self._encoded(text)
            if record["offset"]+len(encoded)>record["limit"]:
                if self.variant!="yellow"or record["offset"]!=0xae655 or not text.endswith("!\\e"):
                    raise RomAuditError("TM text exceeds its source allocation")
                encoded=self._encoded(text[:-3]+"\\e")
            if record["offset"]+len(encoded)>record["limit"]:raise RomAuditError("TM text still exceeds its source allocation")
            self._optional([(record["offset"],encoded)],"TM descriptive text")
        self.profile["tms"]=moves

    def items(self):
        cfg=self.cfg;raw=self.original;pending=[0];visited=set();offsets=set()
        while pending:
            map_id=pending.pop()
            if map_id in visited or map_id in (0xed,0xff):continue
            if not 0<=map_id<256:raise RomAuditError("invalid canonical map id")
            visited.add(map_id)
            bank=raw[cfg["MapBanks"]+map_id]
            header=_pointer(raw,cfg["MapAddresses"]+map_id*2,bank)
            connections=(raw[header+9]&15).bit_count()
            for index in range(connections):pending.append(raw[header+10+index*11])
            objects=_pointer(raw,header+10+connections*11,bank)
            warps=raw[objects+1];cursor=objects+2
            for index in range(warps):pending.append(raw[cursor+index*4+3])
            cursor+=warps*4;signs=raw[cursor];cursor+=1+signs*3
            entities=raw[cursor];cursor+=1
            for _ in range(entities):
                kind=raw[cursor+5]
                if kind&0x40:cursor+=8
                elif kind&0x80 and raw[cursor+6]!=0:offsets.add(cursor+6);cursor+=7
                else:cursor+=6
        root=cfg["SpecialMapPointerTable"];bank=root//0x4000;groups=[]
        if self.variant=="yellow":
            cursor=root
            for _ in range(256):
                if raw[cursor]==255:break
                groups.append(_pointer(raw,cursor+1,bank));cursor+=3
            else:raise RomAuditError("hidden-item map terminator absent")
        else:
            cursor=cfg["SpecialMapList"]
            for index in range(256):
                if raw[cursor+index]==255:break
                groups.append(_pointer(raw,root+index*2,bank))
            else:raise RomAuditError("hidden-item map terminator absent")
        for cursor in set(groups):
            for _ in range(256):
                if raw[cursor]==255:break
                routine=_pointer(raw,cursor+4,raw[cursor+3])
                if routine==cfg["HiddenItemRoutine"]:offsets.add(cursor+2)
                cursor+=6
            else:raise RomAuditError("hidden-item record terminator absent")
        allowed=set(LAYOUT["allowed_items"]);tms=set(LAYOUT["tm_items"])
        result=[]
        for offset in sorted(offsets):
            before=raw[offset]
            if before not in allowed:continue  # HMs/key items remain canonical
            value=self.audit.value(offset,tms if before in tms else allowed-tms,"field/hidden items")
            result.append({"offset":offset,"item":value})
        self.profile["items"]=result

    def serialization(self):
        cfg=self.cfg;offsets=[cfg["IntroPokemonOffset"],cfg["IntroCryOffset"]]
        if any(self.candidate[offset]!=self.original[offset] for offset in offsets):
            species=self.audit.value(offsets[0],self.species,"intro species serialization")
            self.audit.expect(offsets[1],bytes([species]),"intro species serialization")
        text=cfg["TextDelayFunctionOffset"]
        self._optional([(text,b"\xc9")],"Fastest Text")

    def run(self):
        self.wild();self.statics();self.trainers();self.evolutions()
        self.starters();self.tms();self.items();self.serialization()
        return self.audit.finish()|{"profile":self.profile,"complete_semantic_scan":True}


def scan_candidate(original,candidate):
    """Validate all allowed domains and require every other byte to be canonical."""
    return _Scanner(original,candidate).run()


def scan_generated(original,candidate,settings):
    """Also require untouched disabled domains and the selected level modifier."""
    from server.gen1_upr_policy import validate_file
    values=validate_file(settings)
    result=scan_candidate(original,candidate)
    before=scan_candidate(original,original)["profile"];after=result["profile"]
    for setting,domain in (("wildPokemonMod","wild_species"),("staticPokemonMod","statics"),
                           ("tmsMod","tms"),("fieldItemsMod","items")):
        if values[setting]=="UNCHANGED" and after[domain]!=before[domain]:
            raise RomAuditError("disabled setting changed its domain: "+setting)
    if values["startersMod"]=="UNCHANGED":
        own=1 if after["variant"]=="yellow" else 3
        if before["starters"][:own]!=after["starters"][:own]:raise RomAuditError("disabled starter species changed")
    alias=_yellow_rival_record(original) if after["variant"]=="yellow" else None
    for index,(old,new) in enumerate(zip(before["trainers"],after["trainers"])):
        for slot,((old_level,old_species),(level,species)) in enumerate(zip(old["party"],new["party"])):
            if values["trainersMod"]=="UNCHANGED" and old_species!=species:
                # The Yellow rival's first starter is the same physical party
                # byte that its starter option owns. No other alias is exempt.
                if not (after["variant"]=="yellow" and values["startersMod"]!="UNCHANGED"
                        and (index,slot)==alias):
                    raise RomAuditError("disabled trainer species changed")
            modifier=values["trainersLevelModifier"] if values["trainersLevelModified"] else 0
            expected=min(100,math.floor(old_level*(1+modifier/100.0)+0.5))
            if level!=expected:raise RomAuditError("trainer level differs from the selected modifier")
    if not any(values[name] for name in ("changeImpossibleEvolutions","makeEvolutionsEasier","removeTimeBasedEvolutions")):
        if before["evolution_moves"]!=after["evolution_moves"]:raise RomAuditError("disabled evolution methods changed")
    text=LAYOUT["profiles"][after["variant"]]["settings"]["TextDelayFunctionOffset"]
    if candidate[text]!=(0xc9 if values["currentMiscTweaks"]==8 else original[text]):
        raise RomAuditError("Fastest Text differs from selected settings")
    result["settings_sha256"]=hashlib.sha256(settings).hexdigest()
    return result


def _yellow_rival_record(original):
    """Find the documented starter/trainer alias by parsing canonical record slots."""
    cfg=LAYOUT["profiles"]["yellow"]["settings"];root=cfg["TrainerDataTableOffset"]
    target=cfg["StarterOffsets2"][0];index=0
    for group in range(1,48):
        cursor=_pointer(original,root+2*(group-1),root//0x4000)
        for _ in range(cfg["TrainerDataClassCounts"][group]):
            special=original[cursor]==255;cursor+=1;slot=0
            while original[cursor]!=0:
                if cursor+int(special)==target:return index,slot
                cursor+=2 if special else 1;slot+=1
            cursor+=1;index+=1
    raise RomAuditError("Yellow rival starter alias is absent")
