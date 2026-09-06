(function () {
  'use strict';
  var el=SLinkDOM.el, sources=[], presets=[], runs=[], current=null, dirty=false, busy=false, mutation=0, listSignature='';
  var app=JSON.parse(document.getElementById('application-state').textContent);
  var form=document.getElementById('source-editor');
  function message(text){var node=document.getElementById('sources-message');node.hidden=!text;node.textContent=text||'';}
  function options(node,items,value){if(value&&!items.some(function(item){return item[0]===value;}))items=items.concat([[value,'Unavailable: '+value]]);var signature=JSON.stringify(items);if(node.dataset.options!==signature){node.replaceChildren(...items.map(function(item){return el('option',{value:item[0]},item[1]);}));node.dataset.options=signature;}node.value=value||'';}
  function definition(){return presets.find(function(preset){return preset.id===document.getElementById('source-preset').value;});}
  function dependent(values){
    var preset=definition();if(!preset)return;
    options(document.getElementById('source-players'),preset.player_choices.map(function(players){return [players.join(','),players.length===2?'Players A and B':'Player '+players[0].toUpperCase()];}),values.players.join(','));
    document.getElementById('source-player-reason').textContent=preset.player_choices.length===1?'This preset shows both players.':'';
    options(document.getElementById('source-layout'),preset.layouts.map(function(layout){return [layout,({'':'Default',h:'Horizontal','thin-h':'Bottom strip','thin-v':'Sidebar'})[layout]||layout];}),values.layout);
    var controls=document.getElementById('source-controls');controls.replaceChildren();
    ['speed','pause'].forEach(function(key){if(!(key in preset.defaults))return;var input=el('input',{type:'number',name:key,min:key==='speed'?'.1':'0',max:key==='speed'?'5':'30',step:'.1',value:values.controls[key]===undefined?preset.defaults[key]:values.controls[key]});controls.append(el('label',{className:'board-field'},key==='speed'?'Scroll speed':'Pause at each end (seconds)',input));});
    if(preset.event_filters.length){var chosen=values.controls.filter===undefined?preset.defaults.filter:values.controls.filter;var group=el('fieldset',{},el('legend',{},'Events to show'));preset.event_filters.forEach(function(type){var input=el('input',{type:'checkbox',name:'filter',value:type});input.checked=chosen.includes(type);group.append(el('label',{className:'source-filter'},input,type.replaceAll('_',' ')));});controls.append(group);}
    dimensions();
  }
  function dimensions(){var preset=definition();if(!preset)return;var both=preset.player_choices.length>1&&document.getElementById('source-players').value==='a,b';document.getElementById('source-dimensions').textContent=preset.sizes.map(function(size){return both?(size.width*2)+'×'+size.height+' (both players)':size.label;}).join(' · ');}
  document.getElementById('source-players').addEventListener('change',dimensions);
  function renderList(){var signature=JSON.stringify([sources,runs,current&&current.id]);if(signature===listSignature)return;listSignature=signature;var list=document.getElementById('source-list');var focused=document.activeElement&&document.activeElement.dataset.sourceId;list.replaceChildren();sources.forEach(function(source){var run=runs.find(function(item){return item.run_id===source.run_id;});list.append(el('button',{type:'button','data-source-id':source.id,className:'source-list-item'+(current&&source.id===current.id?' active':''),'aria-pressed':String(!!current&&source.id===current.id),onclick:function(){if(canChoose())choose(source);}},el('b',{},source.name),el('small',{},run?run.name+' · '+run.status:'Assigned run was deleted')));});if(!sources.length)list.append(el('p',{className:'board-sub'},'No saved sources yet.'));if(focused){var target=[...list.querySelectorAll('button')].find(function(button){return button.dataset.sourceId===focused;});if(target)target.focus();}}
  function canChoose(){if(busy)return false;if(dirty){message('Save or discard your changes before selecting another source.');return false;}return true;}
  function choose(source){
    current=structuredClone(source);dirty=false;
    form.hidden=false;document.getElementById('sources-empty').hidden=true;
    document.getElementById('source-name').value=current.name;
    options(document.getElementById('source-run'),[['','Choose a run']].concat(runs.map(function(run){return [run.run_id,run.name+' · '+run.status];})),current.run_id);
    options(document.getElementById('source-preset'),presets.map(function(preset){return [preset.id,preset.name];}),current.preset);
    options(document.getElementById('source-theme'),[['transparent','Transparent'],['default','Default'],['light','Light'],['funtastic-grape','Grape'],['funtastic-jungle','Jungle'],['funtastic-fire','Fire'],['funtastic-ice','Ice'],['funtastic-watermelon','Watermelon'],['funtastic-smoke','Smoke']],current.theme);
    dependent(current);
    document.getElementById('source-delete').hidden=!current.id;
    document.getElementById('source-revision').textContent=current.id?'Configuration revision '+current.revision:'New source';
    document.getElementById('source-output').hidden=!current.id;
    if(current.id){var url=location.origin+'/broadcast/sources/'+current.id;document.getElementById('source-url').value=url;document.getElementById('source-open').href=url;var preview=document.getElementById('source-preview');if(preview.getAttribute('src')!==url)preview.src=url;}
    renderList();
  }
  document.getElementById('source-reset').addEventListener('click',function(){if(busy||!current)return;var latest=current.id&&sources.find(function(source){return source.id===current.id;});choose(latest||current);message('Unsaved changes discarded.');});
  form.addEventListener('input',function(){dirty=true;document.getElementById('source-revision').textContent='Unsaved changes';});
  document.getElementById('source-preset').addEventListener('change',function(){var preset=definition();dependent({players:preset.player_choices[0],layout:preset.layouts[0],controls:structuredClone(preset.defaults)});dirty=true;});
  document.getElementById('source-new').addEventListener('click',function(){if(!presets.length||!canChoose())return;var preset=presets[0];choose({name:'',run_id:app.run_id||'',preset:preset.id,players:preset.player_choices[0],layout:preset.layouts[0],theme:'transparent',controls:structuredClone(preset.defaults)});document.getElementById('source-name').focus();});
  form.addEventListener('submit',async function(event){event.preventDefault();if(busy||!current)return;
    var preset=definition(),controls={};['speed','pause'].forEach(function(key){var input=form.querySelector('[name="'+key+'"]');if(input)controls[key]=Number(input.value);});if(preset.event_filters.length)controls.filter=[...form.querySelectorAll('[name=filter]:checked')].map(function(input){return input.value;});
    var body={name:document.getElementById('source-name').value,run_id:document.getElementById('source-run').value,preset:preset.id,players:document.getElementById('source-players').value.split(','),layout:document.getElementById('source-layout').value,theme:document.getElementById('source-theme').value,controls:controls};
    if(current.id)body.revision=current.revision;
    var id=current.id,focused=document.activeElement;mutation++;busy=true;var disabled=[...form.querySelectorAll('input,select,button')].map(function(node){var old=node.disabled;node.disabled=true;return [node,old];});message('Saving source…');
    try{var response=await fetch('/api/broadcast/sources'+(id?'/'+id:''),{method:id?'PATCH':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),data=await response.json();if(!response.ok)throw new Error(data.error||'Source could not be saved.');var index=sources.findIndex(function(item){return item.id===data.source.id;});if(index<0)sources.push(data.source);else sources[index]=data.source;choose(data.source);message('Saved. The OBS URL stays the same when this source changes.');}
    catch(error){message(error.message);}finally{busy=false;disabled.forEach(function(item){if(item[0].isConnected)item[0].disabled=item[1];});if(focused&&focused.isConnected)focused.focus();SLinkPoll.refresh();}
  });
  document.getElementById('source-delete').addEventListener('click',async function(){if(!current||!current.id||busy)return;if(!confirm('Delete saved source “'+current.name+'”? Its OBS URL will show that the source was deleted.'))return;mutation++;busy=true;try{var response=await fetch('/api/broadcast/sources/'+current.id,{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({revision:current.revision})}),data=await response.json();if(!response.ok)throw new Error(data.error);sources=sources.filter(function(source){return source.id!==current.id;});current=null;form.hidden=true;document.getElementById('source-output').hidden=true;document.getElementById('sources-empty').hidden=false;document.getElementById('source-preview').removeAttribute('src');renderList();message('Source deleted.');}catch(error){message(error.message);}finally{busy=false;SLinkPoll.refresh();}});
  document.getElementById('source-copy').addEventListener('click',async function(){try{await navigator.clipboard.writeText(document.getElementById('source-url').value);message('OBS URL copied.');}catch(_){document.getElementById('source-url').select();message('Select and copy the OBS URL.');}});
  SLinkPoll.subscribe('saved-sources',async function(){
    if(busy)return;
    var started=mutation;
    try{
      var response=await fetch('/api/broadcast/sources',{cache:'no-store'}),data=await response.json();
      if(busy||started!==mutation)return;
      if(!response.ok)throw new Error(data.error);
      sources=data.sources;presets=data.presets;runs=data.runs;
      var updated=current&&current.id&&sources.find(function(source){return source.id===current.id;});
      if(updated&&!dirty&&updated.revision>current.revision)choose(updated);
      else{
        renderList();
        if(current){var selected=document.getElementById('source-run').value;options(document.getElementById('source-run'),[['','Choose a run']].concat(runs.map(function(run){return [run.run_id,run.name+' · '+run.status];})),selected);}
      }
      if(current&&current.id&&!updated)message('This source was deleted elsewhere. Your settings remain visible, but this source can no longer be saved.');
      else if(updated&&dirty&&updated.revision!==current.revision)message('This source changed elsewhere. Your unsaved settings are still here; reload before saving.');
    }catch(error){if(!busy&&started===mutation)message(error.message);}
  });
})();
