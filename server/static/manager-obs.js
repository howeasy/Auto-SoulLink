(function () {
  'use strict';
  var el = SLinkDOM.el, config = null, runs = [], dirty = false, busy = false;
  var app = JSON.parse(document.getElementById('application-state').textContent);
  var events = [['battle_start','Battle starts'],['wild_battle_start','Wild battle starts'],['trainer_battle_start','Trainer battle starts'],['battle_end','Battle ends'],['faint','Own Pokémon faints'],['link_death','Partner Pokémon faints'],['whiteout','Whiteout'],['capture','Pokémon caught'],['shiny','Shiny encountered'],['linked','Pair linked'],['dead_zone','Encounter failed'],['area_enter','Enter an area'],['area_enter_new','Enter an open encounter area'],['battle_start_new','New encounter battle'],['party_to_box','Pokémon boxed'],['box_to_party','Pokémon joins party'],['run_over','Run ends'],['memorialize_done','Memorial completed']];
  function message(text) { var node = document.getElementById('obs-message'); node.hidden = !text; node.textContent = text || ''; }
  function changed() { dirty = true; document.getElementById('obs-unsaved').textContent = 'Unsaved changes'; }
  function select(options, value, onchange) {
    var node = el('select', {onchange:onchange});
    options.forEach(function (option) { node.append(el('option',{value:option[0]},option[1])); });
    if (value && !options.some(function (option) { return option[0] === value; })) node.append(el('option',{value:value},'Saved: '+value));
    node.value = value || ''; return node;
  }
  function field(label, input) { return el('label',{className:'board-field'},label,input); }
  function sourceOptions() { return [['','Choose a source run']].concat(runs.map(function (run) { return [run.run_id, run.name+' · '+run.status]; })); }
  function renderRules() {
    var root = document.getElementById('obs-rules'); root.replaceChildren();
    config.rules.forEach(function (rule, index) {
      var enable = el('input',{type:'checkbox'}); enable.checked = rule.enabled; enable.disabled = !rule.run_id;
      var why = el('p',{className:'obs-rule-reason'},rule.run_id ? '' : 'Choose a source run before enabling this rule.');
      enable.addEventListener('change',function(){rule.enabled=enable.checked;changed();});
      var source = select(sourceOptions(),rule.run_id,function(){rule.run_id=source.value||null;enable.disabled=!rule.run_id;if(!rule.run_id){rule.enabled=false;enable.checked=false;}why.textContent=rule.run_id?'':'Choose a source run before enabling this rule.';changed();});
      var event = select(events,rule.event,function(){rule.event=event.value;changed();});
      var player = select([['any','Either player'],['a','Player A'],['b','Player B']],rule.player_filter,function(){rule.player_filter=player.value;changed();});
      var target = select([['own','The triggering player'],['a','Player A OBS'],['b','Player B OBS'],['both','Both OBS connections']],rule.target,function(){rule.target=target.value;changed();});
      var scene = el('input',{type:'text',value:rule.scene,maxlength:'300',oninput:function(){rule.scene=scene.value;changed();}});
      var area = select([['','Any area'],['group:route','Routes'],['group:city','Cities and towns'],['group:cave','Caves and mountains'],['group:forest','Forests'],['group:tower','Towers'],['group:building','Buildings'],['group:water','Water and bridges'],['group:gift','Gifts and events'],['group:other','Other areas']],rule.area_id_filter,function(){rule.area_id_filter=area.value;changed();});
      var areaNote = el('span',{className:'board-sub'},'Connect this run to list exact areas.');
      var loadAreas = async function () {
        if (!rule.run_id) {areaNote.textContent='Choose a source run first.';return;}
        areaNote.textContent='Loading areas…';
        try {
          var response = await fetch('/runs/'+encodeURIComponent(rule.run_id)+'/api/obs/areas');
          if (!response.ok) throw new Error('Start and connect this run to list its areas.');
          var data = await response.json();
          var existing = new Set([...area.options].map(function(option){return option.value;}));
          (data.areas||[]).forEach(function(item){if(!existing.has(item.id))area.append(el('option',{value:item.id},item.name));});
          area.value=rule.area_id_filter;areaNote.textContent='Areas from the chosen source run.';
        } catch(error){areaNote.textContent=error.message;}
      };
      var actions = el('div',{className:'obs-rule-actions'},el('label',{className:'board-opt'},enable,'Enabled'));
      [['Move up',-1],['Move down',1]].forEach(function(pair){
        var button=el('button',{type:'button',className:'board-btn','aria-label':pair[0]+' rule '+(index+1),onclick:function(){var other=index+pair[1];[config.rules[index],config.rules[other]]=[config.rules[other],config.rules[index]];changed();renderRules();}},pair[0]);
        button.disabled=index+pair[1]<0||index+pair[1]>=config.rules.length;actions.append(button);
      });
      actions.append(el('button',{type:'button',className:'board-btn',onclick:function(){config.rules.splice(index,1);changed();renderRules();}},'Remove rule'));
      root.append(el('article',{className:'obs-rule'},el('h3',{},'Rule '+(index+1)),
        el('div',{className:'obs-rule-grid'},field('Source run',source),field('When',event),field('Player',player),field('OBS connection',target),field('Scene name',scene),field('Area',area)),
        el('div',{className:'obs-rule-actions'},el('button',{type:'button',className:'board-btn',onclick:loadAreas},'Load exact areas'),areaNote),why,actions));
    });
    if (!config.rules.length) root.append(el('p',{className:'board-sub'},'No rules yet. Add one and choose its source run.'));
  }
  function renderConfig() {
    document.getElementById('obs-enabled').checked=config.enabled;
    ['a','b'].forEach(function(pid){
      document.getElementById('obs-'+pid+'-host').value=config.connections[pid].host;
      document.getElementById('obs-'+pid+'-port').value=config.connections[pid].port;
      document.getElementById('obs-'+pid+'-password').value='';
      document.getElementById('obs-'+pid+'-clear-password').checked=false;
    });
    renderRules();
  }
  async function load() {
    if(busy)return;
    var selected=document.getElementById('obs-inspect-run').value||app.run_id||'';
    try{
      var response=await fetch('/api/obs/status'+(selected?'?run_id='+encodeURIComponent(selected):''));
      var result=await response.json();if(!response.ok)throw new Error(result.error||'OBS settings are unavailable.');
      if(config&&result.config.revision<config.revision)return;
      runs=result.runs;
      var picker=document.getElementById('obs-inspect-run'), desired=picker.value||app.run_id||'';
      if(document.activeElement!==picker){picker.replaceChildren(...sourceOptions().map(function(option){return el('option',{value:option[0]},option[1]);}));picker.value=desired;}
      if(!config||!dirty&&result.config.revision>config.revision){config=result.config;renderConfig();}
      document.getElementById('obs-revision').textContent='Configuration revision '+result.config.revision;
      if(result.error||result.authority_error)message(result.error||result.authority_error);
      else if(dirty&&config.revision!==result.config.revision)message('Settings changed elsewhere. Your edits are still here; reload before saving.');
      var application=result.applications[picker.value];
      ['a','b'].forEach(function(pid){
        var connection=application&&application.connections&&application.connections[pid];
        document.getElementById('obs-'+pid+'-status').textContent=application&&(application.error||application.forwarding_error)||connection&&connection.status+' · '+(application.applied_revision===null?'settings not applied yet':'applied revision '+application.applied_revision)||'Select a running source run to inspect this connection.';
        document.querySelector('[data-obs-resume="'+pid+'"]').hidden=!result.blocked_endpoints.length;
      });
      var records=document.getElementById('obs-records');records.replaceChildren();
      result.records.forEach(function(record){var run=runs.find(function(item){return item.run_id===record.run_id;});records.append(el('div',{className:'obs-record'},(run?run.name:'Deleted run')+' · Player '+record.player.toUpperCase()+' OBS · '+record.scene+' · '+record.state,el('small',{},'Batch '+record.sequence+' · revision '+record.revision),record.error?el('p',{},record.error):null));});
      if(!result.records.length)records.append('No scene decisions yet.');
      if(result.blocked_endpoints.length)message(result.blocked_endpoints.map(function(item){return item.host+':'+item.port+' — '+item.reason;}).join('\n'));
    }catch(error){message(error.message);}
  }
  document.getElementById('manager-obs').addEventListener('input',function(event){if(event.target.id!=='obs-inspect-run')changed();});
  document.getElementById('obs-inspect-run').addEventListener('change',function(){SLinkPoll.refresh();});
  document.getElementById('obs-add-rule').addEventListener('click',function(){if(!config)return;config.rules.push({id:crypto.randomUUID(),run_id:null,enabled:false,event:'capture',player_filter:'any',target:'own',scene:'',area_id_filter:''});changed();renderRules();});
  document.getElementById('obs-save').addEventListener('click',async function(){
    if(!config||busy)return;
    var body=structuredClone(config);body.enabled=document.getElementById('obs-enabled').checked;
    ['a','b'].forEach(function(pid){var connection=body.connections[pid];connection.host=document.getElementById('obs-'+pid+'-host').value.trim();connection.port=Number(document.getElementById('obs-'+pid+'-port').value);var password=document.getElementById('obs-'+pid+'-password').value;if(password||document.getElementById('obs-'+pid+'-clear-password').checked)connection.password=password;});
    busy=true;var disabled=[...document.querySelectorAll('#manager-obs input,#manager-obs select,#manager-obs button')].map(function(node){var previous=node.disabled;node.disabled=true;return [node,previous];});message('Applying OBS settings…');
    try{var response=await fetch('/api/obs/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});var result=await response.json();if(!response.ok||!result.ok)throw new Error(result.error||'Settings could not be saved.');config=result.config;dirty=false;document.getElementById('obs-unsaved').textContent='Saved';renderConfig();message(result.authority_error||'Saved configuration revision '+config.revision+'. Connection and application results appear below.');}
    catch(error){message(error.message);}finally{busy=false;disabled.forEach(function(item){if(item[0].isConnected)item[0].disabled=item[1];});SLinkPoll.refresh();}
  });
  document.querySelectorAll('[data-obs-resume]').forEach(function(button){button.addEventListener('click',async function(){if(!config)return;var response=await fetch('/api/obs/resume',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({player:button.dataset.obsResume,revision:config.revision})});var result=await response.json();message(result.ok?'Scene changes resumed for this endpoint.':result.error);SLinkPoll.refresh();});});
  document.querySelectorAll('[data-obs-scenes], [data-obs-test]').forEach(function(button){button.addEventListener('click',async function(){
    var run=document.getElementById('obs-inspect-run').value, player=button.dataset.obsScenes||button.dataset.obsTest;
    if(!run){message('Choose a run to inspect or test OBS.');return;}
    button.disabled=true;
    try{
      if(button.hasAttribute('data-obs-scenes')){
        var response=await fetch('/api/obs/scenes/'+player+'?run_id='+encodeURIComponent(run)),result=await response.json();
        if(!response.ok||result.ok===false)throw new Error(result.error||'Scene list unavailable.');
        document.getElementById('obs-'+player+'-scenes').replaceChildren(...(result.scenes||[]).map(function(name){return el('option',{value:name},name);}));message('Scene list refreshed.');
      }else{
        var response=await fetch('/api/obs/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run_id:run,player:player,scene:document.getElementById('obs-'+player+'-test-scene').value})}),result=await response.json();
        if(!response.ok||!result.ok)throw new Error(result.error||'Scene test was not accepted.');message('Scene test queued in batch '+result.sequence+'. Check its application result below.');
      }
    }catch(error){message(error.message);}finally{button.disabled=false;SLinkPoll.refresh();}
  });});
  SLinkPoll.subscribe('manager-obs',load);
})();
