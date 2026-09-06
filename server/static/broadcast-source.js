(function () {
  'use strict';
  var revision = Number(document.body.dataset.sourceRevision), sequence = 0;
  var saved = document.body.dataset.savedSource === 'true';
  var url = new URL(document.body.dataset.fragmentUrl, location.href);
  if (saved) url.searchParams.set('revision', revision);
  function fit() {
    var root=document.getElementById('root'),canvas=root&&root.querySelector('.bc-canvas');
    if(!canvas)return;
    canvas.style.transform='';root.style.height='';
    if(root.dataset.scrollEnabled==='true')return;
    var height=canvas.scrollHeight,width=canvas.scrollWidth;
    var scale=Math.min(1,Math.max(1,innerHeight-12)/Math.max(1,height),Math.max(1,innerWidth-12)/Math.max(1,width));
    if(scale<1){canvas.style.transform='scale('+scale+')';root.style.height=(height*scale+12)+'px';}
  }
  window.addEventListener('resize',fit);
  document.addEventListener('load',fit,true);
  fit();
  function unavailable(message) {
    var root = document.getElementById('root');
    document.getElementById('source-error').hidden=true;
    if (root) { root.dataset.availability='deleted';root.dataset.scrollEnabled='false';root.style.height='';root.replaceChildren(); var note=document.createElement('div');note.className='bc-offline';note.textContent=message;root.append(note); }
  }
  SLinkPoll.subscribe('broadcast-source', async function () {
    var current = ++sequence;
    try {
      var response = await fetch(url.href,{cache:'no-store'});
      if(current!==sequence)return;
      if(response.status===409&&saved){location.reload();return;}
      if(response.status===404||response.status===410){unavailable('This source or its assigned run was deleted.');return;}
      if(!response.ok)throw new Error('Source temporarily unavailable');
      if(saved&&response.headers.get('X-SLink-Source-Revision')!==String(revision)){location.reload();return;}
      var document_ = new DOMParser().parseFromString(await response.text(),'text/html');
      if(current!==sequence)return;
      var incoming=document_.getElementById('root'),root=document.getElementById('root');
      if(!incoming||!root)throw new Error('Source content unavailable');
      if(saved&&Number(incoming.dataset.revision)!==revision){location.reload();return;}
      Idiomorph.morph(root,incoming);
      document.getElementById('source-error').hidden=true;
      if(window.SLinkImages){SLinkImages.processSprites();SLinkImages.processBadges();}
      fit();
    }catch(_){document.getElementById('source-error').hidden=false;}
  });
  // One motion loop for every scrolling component in this document. Position
  // survives morphs; the user may disable motion through the OS preference.
  var previous=0, positions=new Map(), reduced=matchMedia('(prefers-reduced-motion: reduce)');
  function animate(now){
    var delta=Math.min(100,now-(previous||now));previous=now;
    var root=document.getElementById('root');
    if(root&&root.dataset.scrollEnabled==='true'&&!reduced.matches){
      var horizontal=root.classList.contains('preset-ticker'), key=root.className;
      var maximum=horizontal?root.scrollWidth-root.clientWidth:root.scrollHeight-root.clientHeight;
      if(maximum>1){
        var state=positions.get(key)||{offset:0,direction:1,wait:0};
        var speed=Number(root.dataset.scrollSpeed)||1, pause=Number(root.dataset.scrollPause)||0;
        if(state.wait>0)state.wait-=delta;
        else{state.offset+=state.direction*delta*.022*speed;if(state.offset>=maximum||state.offset<=0){state.offset=Math.max(0,Math.min(maximum,state.offset));state.direction*=-1;state.wait=pause*1000;}}
        if(horizontal)root.scrollLeft=state.offset;else root.scrollTop=state.offset;
        positions.set(key,state);
      }
    }
    requestAnimationFrame(animate);
  }
  requestAnimationFrame(animate);
})();
