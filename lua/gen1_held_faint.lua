-- Generation binding of a one-use write permit to an independently held party.
local JSON=require("json_codec")
local Canonical=require("journal_document")
local Receipts=require("gen1_command_receipts")
local Permit=require("held_write_permit")
local Rival=require("gen1_held_rival_team")
local M={}
function M.handles(body)
    return type(body)=="table"and(body.cmd=="initial_save"or type(body.job_id)=="string"
        and(body.cmd=="storage_observe"or body.cmd=="storage_apply")or type(body.acquisition_id)=="string"
        and(body.cmd=="retirement_observe"or body.cmd=="acquisition_retire")or type(body.death_id)=="string"
        and(body.cmd=="force_faint"or body.cmd=="force_explode"or body.cmd=="memorialize"or body.cmd=="memorial_observe")or Rival.handles(body))
end
local function is_read(body)return body.cmd=="memorial_observe"or body.cmd=="retirement_observe"or body.cmd=="storage_observe"end
local function is_death(body)return body.cmd=="force_faint"or body.cmd=="force_explode"end
local EXPLODE_RECEIPT="gen1-force-explode-receipt-v1"  -- server: gen1_command_receipts.RECEIPT_SCHEMAS
local function copy(v)return assert(JSON.decode(assert(JSON.encode(v))))end
local function same(a,b)return Canonical.encode(a)==Canonical.encode(b)end
function M.new(options)
    local journal,mem,owned,host=options.journal,options.memory,options.owned,options.host
    local self={binding=nil,current=nil,pending_proof=nil,pending_request=nil}
    local function sha(value)return journal.store.backend.sha256(assert(Canonical.encode(value)))end
    local function refresh()
        local revision=journal.store.revision and assert(journal.store:revision())
        if revision~=nil and self.revision==revision then return end
        local entry=assert(journal:pending_commands())[1]
        if not entry or not self.current or entry.command_id~=self.current.command_id then self.memorial_phase=nil end
        if entry then entry=copy(entry);entry.body=require("gen1_runtime").unwrap(entry.body,options.player)end
        if entry and M.handles(entry.body)then self.current=entry else self.current=nil end
        self.revision=revision
        self.command_digest=self.current and sha({command_id=entry.command_id,command_sequence=entry.command_sequence,body=entry.body})or nil
    end
    local function scope()
        refresh();local entry=self.current
        if not self.binding or not entry or not entry.intent or is_read(entry.body)then return nil end
        return {operation_id=entry.command_id,operation_digest=self.command_digest,context_generation=owned().context_generation,
            binding_digest=self.binding.binding_digest,phase=self.memorial_phase or entry.body.cmd}
    end
    local permit=Permit.new({clock=options.clock,current_scope=scope,
        verify_grant=function(packet)return self.pending_proof~=nil and packet.proof_digest==self.pending_proof end})
    local rival=Rival.new({memory=mem,variant=options.variant})
    local function safe()
        owned();local held=host.status().physical_stop_verified
        if self.current and Rival.handles(self.current.body)then return rival.safe(self.current.body) and held end
        return mem.isPartyWriteSafe() and held
    end
    local function readable(body)
        if body.cmd=="storage_observe"then owned();return host.status().physical_stop_verified end
        return safe()
    end
    local adapter=require("gen1_force_faint_executor").new(mem,options.variant,owned().save_identity,safe)
    -- force_explode at the verified overworld checkpoint is the faint write (gen3_frlge_client.lua:790-796,
    -- gen1_rby_client.lua:322-334 do the same out of battle): the faint executor sees a force_faint body,
    -- the receipt names force_explode so the server settles that command and no other.
    local explode={}
    for _,name in ipairs({"prepare","classify","apply","receipt"})do
        explode[name]=function(body,...)
            local faint=copy(body);faint.cmd="force_faint"
            local result,why=adapter[name](faint,...)
            if name=="receipt" and result then result.schema=EXPLODE_RECEIPT end
            return result,why
        end
    end
    local memorial=require("gen1_held_memorial").new({memory=mem,variant=options.variant,owned=owned,host=host,
        safe=safe,sha=sha,saveram_path=options.saveram_path,saveram_directory=options.saveram_directory,
        permitted=function()return permit:valid()==true and permit:status().used end})
    local initial=require("gen1_held_initial_save").new({memory=mem,variant=options.variant,owned=owned,host=host,
        safe=safe,sha=sha,saveram_path=options.saveram_path,saveram_directory=options.saveram_directory,
        permitted=function()return permit:valid()==true and permit:status().used end})
    local retirement=require("gen1_held_retirement").new({memory=mem,variant=options.variant,owned=owned,host=host,
        safe=safe,sha=sha,saveram_path=options.saveram_path,saveram_directory=options.saveram_directory,
        permitted=function()return permit:valid()==true and permit:status().used end})
    local storage=require("gen1_held_storage").new({memory=mem,variant=options.variant,owned=owned,host=host,
        safe=safe,sha=sha,saveram_path=options.saveram_path,saveram_directory=options.saveram_directory,
        permitted=function()return permit:valid()==true and permit:status().used end})
    local function is_image(body)return body.cmd=="memorialize"or body.cmd=="initial_save"or body.cmd=="acquisition_retire"or body.cmd=="storage_apply"end
    local function phases(body)
        if body.cmd=="initial_save" then return {apply="initial_save",save="initial_save_flush",repair="initial_save_repair"}end
        if body.cmd=="acquisition_retire"then return {apply="acquisition_retire",save="retirement_save",repair="retirement_repair"}end
        if body.cmd=="storage_apply"then return {apply="storage_apply",save="storage_save",repair="storage_repair"}end
        return {apply="memorialize",save="memorial_save",repair="memorial_repair"}
    end
    local function selected(body)
        if Rival.handles(body)then return rival end
        if body.cmd=="force_faint"then return adapter end
        if body.cmd=="force_explode"then return explode end
        if body.cmd=="acquisition_retire"or body.cmd=="retirement_observe"then return retirement end
        if body.cmd=="storage_apply"or body.cmd=="storage_observe"then return storage end
        return body.cmd=="initial_save" and initial or memorial
    end
    local function matches(body)
        refresh();return self.current~=nil and same(self.current.body,body)
    end
    -- Answer whether the head command is at its route-specific checkpoint before
    -- the outer free loop takes the physical hold. Rival Swap is intentionally
    -- an in-battle write and therefore cannot use the generic overworld party
    -- predicate; taking the hold before its exact battle-init checkpoint would
    -- freeze the core before the command can ever become ready.
    self.pending=function()
        refresh()
        if not self.current then return false end
        if Rival.handles(self.current.body)then return rival.safe(self.current.body)==true end
        return mem.isPartyWriteSafe()==true
    end
    self.adapter={}
    for _,name in ipairs({"prepare"})do
        self.adapter[name]=function(body,...)
            assert(matches(body) and readable(body),"owned held faint command required")
            return selected(body)[name](body,...)
        end
    end
    self.adapter.classify=function(body,intent,identity)
        assert(matches(body) and readable(body),"owned held faint command required")
        if not is_read(body)and permit:valid()~=true then
            return "armed",{schema="rby-held-faint-awaiting-permit-v1",command_id=identity.command_id}
        end
        local state,observed=selected(body).classify(body,intent,identity)
        if is_image(body) and state=="after" and self.memorial_phase~=phases(body).save then
            self.memorial_phase=phases(body).save;permit:revoke()
            return "armed",{schema="rby-memorial-awaiting-save-permit-v1",command_id=identity.command_id}
        end
        return state,observed
    end
    self.adapter.apply=function(body,intent,...)
        assert(matches(body) and safe() and permit:valid()==true and permit:status().used,"held faint lacks consumed write permission")
        local frame=emu.framecount();local result=selected(body).apply(body,intent,...)
        if is_image(body) and result==false then
            assert(safe() and emu.framecount()==frame,"partial memorial lost its owned hold");permit:revoke();return
        end
        assert(safe() and emu.framecount()==frame and permit:valid()==true,"held faint authority changed during write")
        return result
    end
    self.adapter.receipt=function(body,intent,...)
        if is_read(body)then assert(matches(body)and readable(body));return selected(body).receipt(body,intent,...)end
        assert(matches(body) and safe() and permit:valid()==true,"held faint receipt needs fresh command authority")
        if not permit:status().used then assert(permit:consume(),"held no-op receipt permission unavailable")end
        local result=selected(body).receipt(body,intent,...)
        assert(safe() and permit:valid()==true,"held faint authority changed during receipt")
        return result
    end
    self.ready=function(body,intent,control)
        if not matches(body) or not control.admitted or not control.held or not readable(body)then return false,"waiting for owned held faint command"end
        if body.cmd=="retirement_observe"or body.cmd=="storage_observe"then return true end
        if body.cmd=="memorial_observe" then
            if mem.getPartyCount()<1 then return false,"memorial read requires an existing party member"end
            for slot=0,mem.getPartyCount()-1 do
                local mon=mem.readPartySlot(slot)
                if mon and mon.key==body.key then return mon.hp==0,"waiting for physical actor faint completion"end
            end
            return false,"memorial target is not in the party"
        end
        if is_image(body)then selected(body).prepare_host()end
        if intent then return permit:valid()==true,"waiting for server held-write permit"end
        return true
    end
    self.operations={
        request=function(binding,control)
            self.binding=copy(binding);refresh()
            if not control.admitted or not control.held or not safe()then return nil end
            local current_point
            if self.current and is_image(self.current.body) and self.current.intent then
                current_point=require("gen1_full_save").capture(mem,options.variant)
                self.memorial_phase=selected(self.current.body).phase(current_point,self.current.body.payload)
            end
            local selected=scope()
            if not selected or not control.admitted or not control.held or not safe()then return nil end
            local entry=self.current;local status=host.status()
            local evidence={schema=Rival.handles(entry.body) and Rival.EVIDENCE or is_death(entry.body) and "rby-held-faint-evidence-v1" or (entry.body.cmd=="initial_save" and "rby-held-initial-save-evidence-v1" or entry.body.cmd=="acquisition_retire"and"rby-held-retirement-evidence-v1"or entry.body.cmd=="storage_apply"and"rby-held-storage-evidence-v1"or "rby-held-memorial-evidence-v1"),command_id=entry.command_id,command_sequence=entry.command_sequence,
                context_generation=owned().context_generation,final_sha1=gameinfo.getromhash():lower(),
                host={owner_id=status.owner_id,capability_id=status.capability_id,process_id=status.process_id,
                    frame=emu.framecount(),held=status.physical_stop_verified==true},
                checkpoint=Rival.handles(entry.body) and rival.checkpoint(entry.body) or require("gen1_write_checkpoint").capture(mem.profile),intent=copy(entry.intent),
                current=Rival.handles(entry.body) and rival.image(entry.body) or is_death(entry.body) and assert(Receipts.party_snapshot(mem,options.variant)) or current_point}
            if is_image(entry.body)then evidence.phase=self.memorial_phase or phases(entry.body).apply end
            self.pending_proof=sha(evidence);self.pending_request=assert(permit:challenge())
            self.pending_sequence=entry.command_sequence
            return {window=copy(self.pending_request),evidence=evidence}
        end,
        accept=function(packet)
            if packet==nil then permit:revoke();self.pending_request=nil;self.pending_proof=nil;return true end
            local request=self.pending_request
            if request and not same(scope(),request.scope)then
                local state=assert(journal.store:read());local entry=journal:get_command(request.scope.operation_id)
                local p=self.current and phases(self.current.body)
                local transitioned=self.current and is_image(self.current.body) and self.current.command_id==request.scope.operation_id
                    and (request.scope.phase==p.apply or request.scope.phase==p.repair)
                    and (self.memorial_phase==p.save or self.memorial_phase==p.repair)
                    and selected(self.current.body).phase(require("gen1_full_save").capture(mem,options.variant),self.current.body.payload)==self.memorial_phase
                assert(packet.schema==Permit.SCHEMA and packet.uses==1 and packet.challenge==request.challenge
                    and same(packet.scope,request.scope) and packet.proof_digest==self.pending_proof
                    and (transitioned or (entry and entry.outcome=="ACK") or state.command_floor>=self.pending_sequence),
                    "obsolete permit lacks exact durable completion")
                permit:revoke();self.pending_request=nil;self.pending_proof=nil;return true
            end
            local ok,why=permit:accept(packet);self.pending_request=nil;self.pending_proof=nil;return ok,why
        end,
        authorize_apply=function(body,intent,identity,control)
            return control.admitted and control.held and matches(body) and safe() and self.current.command_id==identity.command_id
                and self.current.command_sequence==identity.command_sequence and same(self.current.intent,intent) and permit:consume()==true,
                "fresh single-use held faint permission required"
        end,
        revoke=function()self.binding=nil;self.pending_proof=nil;self.pending_request=nil;permit:revoke()end,
        status=function()return permit:status()end}
    return self
end
return M
