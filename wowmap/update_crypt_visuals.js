/* Visual-only update for an already imported DEV2-R4. No HP, uses or encounter reset. */
(function(root) {
  'use strict';
  function planActor(actor, source, prototype=false) {
    const update={img:source.img};
    if(prototype) update['prototypeToken.texture.src']=source.prototypeToken.texture.src;
    const byIdentifier=new Map(source.items.map(i=>[i.system.identifier,i]));
    const items=[];
    for(const item of actor.items) {
      const original=byIdentifier.get(item.system.identifier);
      if(!original) continue; // Preserve custom items and removed source abilities.
      const change={_id:item.id,img:original.img};
      const activities=item.toObject ? item.toObject().system.activities : item.system.activities;
      for(const id of Object.keys(activities || {})) {
        if(original.system.activities?.[id]) change[`system.activities.${id}.img`]=original.system.activities[id].img;
      }
      items.push(change);
    }
    return {actor,update,items};
  }
  async function updateCryptVisuals(env,bundle) {
    if(!env.game.user.isGM) throw Error('Обновление доступно только мастеру.');
    const packageId='void-crypt-dev2-r4';
    if(bundle.format!=='wowmap.foundry/1' || bundle.mediaRoot!==`wowmap/${packageId}` || bundle.visualRevision!=='R4.1')
      throw Error('Нужен обновлённый пакет крипты R4.1. Сначала скопируйте папку wowmap в Data.');
    const sources=new Map(bundle.actors.map(a=>[a.flags.wowmap.key,a]));
    const worlds=[...env.game.actors].filter(a=>a.flags?.wowmap?.package===packageId && sources.has(a.flags.wowmap.key));
    if(!worlds.length) throw Error('Импортированные NPC крипты DEV2-R4 не найдены. Для первого импорта используйте import-foundry.js.');
    const plans=worlds.map(a=>planActor(a,sources.get(a.flags.wowmap.key),true));
    const tokens=[];
    for(const scene of env.game.scenes) for(const token of scene.tokens) {
      const actor=token.actor,key=actor?.flags?.wowmap?.key;
      if(actor?.flags?.wowmap?.package!==packageId || !sources.has(key)) continue;
      const source=sources.get(key);
      tokens.push({token,image:source.prototypeToken.texture.src});
      if(!token.actorLink) plans.push(planActor(actor,source));
    }
    // Preflight images before the first mutation; a missing copy must fail early.
    const media=new Set();
    for(const p of plans) {media.add(p.update.img);for(const i of p.items) media.add(i.img);}
    for(const t of tokens) media.add(t.image);
    for(const file of media) {
      if(!file.startsWith('wowmap/content/')) throw Error('Некорректный путь изображения.');
      const response=await env.fetch(file,{method:'HEAD',cache:'no-store'});
      if(!response.ok) throw Error(`Изображение недоступно: ${file}. Скопируйте папку wowmap в Data.`);
    }
    for(const p of plans) {
      await p.actor.update(p.update);
      if(p.items.length) await p.actor.updateEmbeddedDocuments('Item',p.items);
    }
    for(const t of tokens) await t.token.update({'texture.src':t.image});
    env.ui.notifications.info(`Крипта R4.1: обновлены изображения ${worlds.length} NPC и ${tokens.length} токенов. Хиты и ресурсы сохранены.`);
    return {actors:worlds.length,tokens:tokens.length};
  }
  if(typeof module!=='undefined' && module.exports) module.exports={updateCryptVisuals};
  else (async()=>{
    try {
      const response=await fetch('wowmap/void-crypt-dev2-r4/bundle.json',{cache:'no-store'});
      if(!response.ok) throw Error('Не найден bundle.json крипты.');
      await updateCryptVisuals({game,ui,fetch},await response.json());
    } catch(error) {console.error(error);ui.notifications.error(error.message);}
  })();
})(globalThis);
