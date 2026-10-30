// GM helper for a prepared crypt encounter. No hooks or automatic attack AI.
function createCryptController(env, cfg) {
  const clone = value => JSON.parse(JSON.stringify(value));
  const box = token => ({x:token.x,y:token.y,w:token.width,h:token.height});
  const overlaps = (a,b,grid) => a.x < b.x+b.w*grid && a.x+a.w*grid > b.x && a.y < b.y+b.h*grid && a.y+a.h*grid > b.y;
  return async function execute(op) {
    if (!env.game.user.isGM) throw Error('Помощник доступен только мастеру.');
    const scene = env.canvas.scene;
    if (!scene || scene.flags?.wowmap?.package !== cfg.package || scene.flags?.wowmap?.key !== 'crypt-sanctum')
      throw Error('Откройте финальный зал DEV2-R4.');
    const boss = scene.tokens.find(t => t.actorId === cfg.actors.vaelis);
    if (!boss) throw Error('Токен Ваэлиса не найден.');
    const state = clone(boss.flags?.wowmap?.cryptState || {phase:1,started:0});
    const save = () => boss.update({'flags.wowmap.cryptState':state});
    const hp = token => Number(token.actor?.system?.attributes?.hp?.value || 0);
    const combat = env.game.combat;
    const say = content => env.ChatMessage.create({content:'<p><b>Крипта Бездны.</b> '+content+'</p>'});
    const bossTurn = () => {
      if (!combat || combat.scene?.id !== scene.id || combat.combatant?.tokenId !== boss.id)
        throw Error('Сначала выберите текущий ход Ваэлиса в бою этой сцены.');
      if (hp(boss)<=0) throw Error('Ваэлис погиб; новые волны недоступны.');
      if (state.phase!==2) throw Error('Сначала включите вторую фазу.');
    };
    const summoned = () => scene.tokens.filter(t => t.flags?.wowmap?.cryptSummon?.boss === boss.id && hp(t)>0);
    const portal = slot => scene.tokens.get(state.pending?.rifts?.[slot]);
    if (op==='status') {
      env.ui.notifications.info(`Фаза ${state.phase}; волн подготовлено ${state.started}/2; живых подкреплений ${summoned().length}/3; ожидает волна ${state.pending?.wave || 'нет'}.`);
      return clone(state);
    }
    if (op==='phase') {
      if (state.phase===2) throw Error('Вторая фаза уже включена.');
      if (hp(boss)<=0 || hp(boss)>150) throw Error('Переход доступен живому Ваэлису при 150 или меньше хитов.');
      state.phase=2;
      await boss.update({'flags.wowmap.cryptState':state,'texture.tint':'#c99aff'});
      await say('Руны теряют симметрию. «Нет. Расчёт верен. Это вас нужно исправить». Фаза II. Хиты и ресурсы не восстановлены. Отмените незаконченный удар фазы I вручную.');
      return;
    }
    if (op==='end') {
      const ids=(state.pending?.rifts || []).filter(id=>scene.tokens.get(id));
      if (ids.length) await scene.deleteEmbeddedDocuments('Token',ids);
      delete state.pending;state.ended=true;await save();
      await say('Незавершённые разломы закрыты. Уже появившиеся существа остаются; новые волны не возникают.');
      return;
    }
    if (op==='close0' || op==='close1') {
      if (!state.pending) throw Error('Открытых разломов нет.');
      const slot=op==='close0'?0:1;const p=portal(slot);
      if (!p) throw Error('Этот разлом уже закрыт.');
      // GM chooses this only after the stated successful check/dispel/attack.
      await scene.deleteEmbeddedDocuments('Token',[p.id]);
      await say(`Разлом ${slot+1} закрыт. Его подкрепление не появится.`);
      return;
    }
    bossTurn();
    if (state.ended) throw Error('Ритуал уже окончен.');
    if (op==='warn') {
      if (state.pending) throw Error('Сначала разрешите предыдущую волну.');
      if (state.started>=2) throw Error('Обе волны уже использованы.');
      if (state.lastWarningRound!==undefined && combat.round-state.lastWarningRound<2)
        throw Error('Между подготовками волн должно пройти не менее двух раундов.');
      if (summoned().length>=3) throw Error('Достигнут предел трёх живых подкреплений.');
      const wave=state.started+1;
      // Also catches a partial earlier write; do not silently create duplicates.
      if (scene.tokens.some(t=>t.flags?.wowmap?.cryptRift?.boss===boss.id && t.flags.wowmap.cryptRift.wave===wave))
        throw Error('На сцене уже есть разломы этой волны. Проверьте её состояние.');
      const riftActor=env.game.actors.get(cfg.actors.rift);
      if (!riftActor) throw Error('Actor разлома отсутствует.');
      const docs=[];
      for (let slot=0;slot<2;slot++) {
        const [cx,cy]=cfg.rifts[slot],grid=scene.grid.size;
        const doc=await riftActor.getTokenDocument({name:`Разлом ${slot+1} — волна ${wave}`,x:(cx-.5)*grid,y:(cy-.5)*grid,
          width:1,height:1,actorLink:false,hidden:false,flags:{wowmap:{cryptRift:{boss:boss.id,wave,slot}}}});
        const data=doc.toObject();delete data._id;docs.push(data);
      }
      const created=await scene.createEmbeddedDocuments('Token',docs);
      if (created.length!==2) throw Error('Создана лишь часть разломов; проверьте сцену, не запускайте волну повторно.');
      state.pending={wave,round:combat.round,rifts:created.map(t=>t.id)};
      state.started=wave;state.lastWarningRound=combat.round;await save();
      const item=boss.actor.items.find(i=>i.system?.identifier==='vaelis-wave');
      if (item) await item.update({'system.uses.spent':wave});
      await say(`Волна ${wave}: загораются две руны. У каждой КД 13 и 12 хитов; закрытие из соседней клетки — действие и Магия Сл 14, либо рассеивание эффекта 3 круга. Выпуск — действием в начале следующего хода Ваэлиса. Подготовка уже расходует действие и использование: не нажимайте дополнительно кнопку расхода в листе.`);
      return;
    }
    if (op!=='tick') throw Error('Неизвестная команда.');
    // Existing reserves join only after a full round following their creation.
    const ready=summoned().filter(t=>t.flags.wowmap.cryptSummon.readyRound<=combat.round && !combat.combatants.some(c=>c.tokenId===t.id));
    if (ready.length) await combat.createEmbeddedDocuments('Combatant',ready.map(t=>({tokenId:t.id,sceneId:scene.id,actorId:t.actorId,hidden:t.hidden,
      initiative:(Number(combat.combatant.initiative)||0)-.01})));
    if (!state.pending) {
      env.ui.notifications.info(`Готовых подкреплений введено в инициативу: ${ready.length}. Ожидающей волны нет.`);return;
    }
    if (combat.round<=state.pending.round) throw Error('Сначала должен пройти полный круг инициативы.');
    const pending=state.pending;
    if (scene.tokens.some(t=>t.flags?.wowmap?.cryptSummon?.boss===boss.id && t.flags.wowmap.cryptSummon.wave===pending.wave))
      throw Error('Подкрепления этой волны уже существуют. Проверьте сцену; повторное создание остановлено.');
    let allowance=3-summoned().length;
    const docs=[],grid=scene.grid.size,occupied=scene.tokens.filter(t=>hp(t)>0 && !t.flags?.wowmap?.cryptRift).map(box);
    for (let slot=0;slot<2;slot++) {
      const p=portal(slot);
      if (!p || hp(p)<=0 || allowance<=0) continue;
      const key=pending.wave===2 && slot===0?'voidguard':'echo';
      const actor=env.game.actors.get(cfg.actors[key]);if (!actor) throw Error('Нет Actor подкрепления: '+key);
      const size=key==='voidguard'?2:1;
      const points=cfg.safePoints[String(size)][slot];
      const point=points.find(([cx,cy])=>!occupied.some(o=>overlaps({x:(cx-size/2)*grid,y:(cy-size/2)*grid,w:size,h:size},o,grid)));
      if (!point) throw Error('Место призыва занято. Освободите пространство у разлома; волна пока не выпущена.');
      const [cx,cy]=point;
      const token=await actor.getTokenDocument({name:actor.name,x:(cx-size/2)*grid,y:(cy-size/2)*grid,width:size,height:size,
        actorLink:false,hidden:false,flags:{wowmap:{cryptSummon:{boss:boss.id,wave:pending.wave,readyRound:combat.round+1}}}});
      const data=token.toObject();delete data._id;docs.push(data);occupied.push(box(data));allowance--;
    }
    // All slots have been checked before any writes. A token is never placed
    // inside another token, and candidate points were prechecked against walls.
    if (docs.length) {
      const created=await scene.createEmbeddedDocuments('Token',docs);
      if (created.length!==docs.length) throw Error('Волна создана частично; повторный выпуск остановлен до ручной проверки.');
    }
    const ids=pending.rifts.filter(id=>scene.tokens.get(id));
    if (ids.length) await scene.deleteEmbeddedDocuments('Token',ids);
    delete state.pending;await save();
    await say(`Волна ${pending.wave} разрешена действием Ваэлиса: появилось ${docs.length} существ. Закрытые разломы и лимит учтены. Новые существа пока НЕ действуют. В начале следующего хода Ваэлиса снова нажмите «Начало хода»: помощник введёт их в инициативу после босса.`);
  };
}

if (typeof module!=='undefined' && module.exports) module.exports={createCryptController};
else (async()=>{
  try {
    if (!game.user.isGM) throw Error('Только для мастера.');
    const op=await foundry.applications.api.DialogV2.prompt({window:{title:'Крипта — Ваэлис'},
      content:'<label>Действие<select name="op"><option value="status">Состояние</option><option value="phase">Включить фазу II (≤150 хитов)</option><option value="warn">Подготовить следующую волну — действие</option><option value="tick">Начало хода: выпустить волну / ввести подкрепления</option><option value="close0">Разлом 1: закрыт успешным действием</option><option value="close1">Разлом 2: закрыт успешным действием</option><option value="end">Закрыть незавершённый ритуал</option></select></label>',
      ok:{label:'Выполнить',callback:(event,button)=>button.form.elements.op.value},rejectClose:false});
    if (op) await createCryptController(globalThis,__CRYPT_CONFIG__)(op);
  } catch(error) {console.error('Crypt encounter',error);ui.notifications.error(error.message,{permanent:true});}
})();
