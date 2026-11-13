{
const registration = Symbol.for('foundry-content-generator.resource-pools');
if (!globalThis[registration]) {
globalThis[registration] = { version: 5 };
const NS = 'foundry-content-generator';
const configFor = x => foundry.utils.getProperty(x, `flags.${NS}.resourcePool`);
function number(formula, actor) {
  const text=String(formula ?? '').trim();
  if (!text) throw Error('Пустая формула ресурса');
  const n=Number(text);
  const result=Number.isFinite(n) ? n : Number(Roll.safeEval(Roll.replaceFormulaData(text,actor.getRollData(),{missing:'0'})));
  if (!Number.isFinite(result) || result<0) throw Error(`Некорректная формула ресурса: ${text}`);
  return result;
}
// The system applies these updates together with native item uses.
// Running on activityConsumption avoids spending resources when the usage dialog is canceled.
Hooks.on('dnd5e.activityConsumption', (activity, usage, message, updates) => {
  const cfg=configFor(activity);
  if (!cfg?.key) return;
  try {
    const actor=activity.item?.actor ?? activity.actor;
    const pools=actor?.items.filter(i=>configFor(i)?.key===cfg.key) ?? [];
    if (pools.length!==1) throw Error(`Для «${cfg.key}» требуется ровно один владелец ресурса.`);
    const pool=pools[0], max=number(pool.system.uses.max,actor);
    updates.item ??= [];
    let update=updates.item.find(i=>i._id===pool.id);
    const original=update?.['system.uses.spent'] ?? pool.system.uses.spent ?? 0;
    const spent=Math.min(max,Math.max(0,Number(original))), remaining=max-spent;
    const cost=number(cfg.cost ?? 1,actor), operation=cfg.operation ?? 'consume';
    if (!['consume','restore','clear','raise','consumeAll'].includes(operation)) throw Error(`Неизвестная операция ${operation}`);
    if (operation==='consume' && cfg.maxCost!==undefined && cost>number(cfg.maxCost,actor)) throw Error('Превышен предел расхода за одно применение');
    if (cfg.requireEmpty && remaining>0) throw Error(`«${cfg.key}»: запас должен быть пуст.`);
    if (operation==='consume' && remaining<cost) throw Error(`«${cfg.key}»: требуется ${cost}, доступно ${remaining}.`);
    if (operation==='consumeAll' && remaining<=0) throw Error(`«${cfg.key}»: запас пуст.`);
    const next=operation==='raise' ? max-Math.min(max,Math.max(remaining,cost)) : operation==='consumeAll' ? max : operation==='clear' ? max : operation==='restore' ? Math.max(0,spent-cost) : spent+cost;
    // Optional fixed ordinary spell-slot exchange. Validate before mutating either resource.
    if (cfg.slot) {
      const level=Number(cfg.slot.level), direction=cfg.slot.operation;
      if (!Number.isInteger(level) || level<1 || level>9 || !['consume','restore'].includes(direction)) throw Error('Некорректный обмен ячейки');
      if (cfg.slot.maxLevel!==undefined && level>number(cfg.slot.maxLevel,actor)) throw Error('Круг ячейки превышает разрешённый предел');
      const path=`system.spells.spell${level}.value`;
      const value=Number(updates.actor?.[path] ?? actor.system?.spells?.[`spell${level}`]?.value ?? 0);
      if (!Number.isFinite(value) || value<0) throw Error('Некорректный запас ячеек');
      if (direction==='restore' && cfg.slot.requireExpended) {
        const slotMax=Number(actor.system?.spells?.[`spell${level}`]?.max ?? 0);
        if (!Number.isFinite(slotMax) || slotMax<=0 || value>=slotMax) throw Error('Нет потраченной ячейки этого круга');
      }
      if (direction==='consume' && value<1) throw Error(`Нет обычной ячейки ${level}-го круга`);
      updates.actor ??= {};
      updates.actor[path]=value+(direction==='restore' ? 1 : -1);
    }
    if (!update) { update={_id:pool.id};updates.item.push(update); }
    update['system.uses.spent']=next;
  } catch(error) { ui.notifications.error(error.message); return false; }
});
Hooks.on('preCreateItem',(item)=>{
  const cfg=configFor(item), actor=item.actor ?? item.parent;
  if (!cfg?.initialEmpty || !actor?.getRollData) return;
  try { item.updateSource({'system.uses.spent':number(item.system.uses.max,actor)}); }
  catch(error) { ui.notifications.error(error.message);return false; }
});

}
}
