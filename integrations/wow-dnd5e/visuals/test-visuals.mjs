import assert from 'node:assert/strict';
import {BINDINGS} from '../scripts/warcraft-visual-bindings.mjs';
import {visualFor,onUse,sourceFor} from '../scripts/warcraft-visuals.mjs';
const events=[];let enabled=true;
globalThis.Sequence=class {
 constructor(){this.row={};events.push(this.row);}
 effect(){return this;}file(x){this.row.file=x;return this;}atLocation(x){this.row.from=x;return this;}
 moveTowards(x){this.row.to=x;return this;}moveSpeed(){return this;}duration(){return this;}
 template(x){this.row.template=x;return this;}stretchTo(x,o){this.row.to=x;this.row.stretch=o;return this;}scale(x){this.row.scale=x;return this;}
 size(x){this.row.size=x;return this;}spriteAnchor(x){this.row.anchor=x;return this;}fadeIn(){return this;}fadeOut(){return this;}async play(){this.row.played=true;}
};
globalThis.game={release:{generation:13},system:{id:'dnd5e',version:'5.3.3'},user:{id:'u',isGM:true,targets:new Set()},modules:new Map([['sequencer',{active:true}]]),settings:{get:()=>enabled}};
const warnings=[];globalThis.ui={notifications:{warn:x=>warnings.push(x)}};
const actor={uuid:'Actor.test'};
const source={actor,controlled:true,center:{x:100,y:100},isVisible:true,document:{isOwner:true,uuid:'source',parent:{id:'scene'}}};
const target={actor:{uuid:'Actor.target'},center:{x:800,y:100},isVisible:true,document:{uuid:'target',parent:{id:'scene'}}};
globalThis.canvas={ready:true,scene:{id:'scene'},grid:{size:100},tokens:{placeables:[source]}};
let counter=0;
const results=(templates=[])=>({message:{uuid:'ChatMessage.'+(++counter),author:{id:'u'}},templates});
function activity(uuid,aid){return {id:aid,type:BINDINGS[uuid].activities[aid].activityType,actor,item:{id:uuid.split('.').at(-1),actor,_stats:{compendiumSource:uuid},getFlag:()=>undefined}};}
const tokens=Object.entries(BINDINGS).filter(([,v])=>Object.values(v.activities).some(x=>x.mode==='token'));
const areas=Object.entries(BINDINGS).filter(([,v])=>Object.values(v.activities).some(x=>x.mode==='template'));
assert.equal(Object.values(BINDINGS).reduce((n,x)=>n+Object.keys(x.activities).length,0),144);
assert.equal(areas.length,2);
for(const [uuid,row] of Object.entries(BINDINGS)){
 for(const aid of Object.keys(row.activities)){
  const a=activity(uuid,aid);assert.ok(visualFor(a));
  assert.equal(visualFor({...a,id:'repeat-damage'}),null);
  assert.equal(visualFor({...a,type:'utility'}),null);
 }
}
const [uuid,row]=tokens[0];const aid=Object.keys(row.activities)[0];const a=activity(uuid,aid);
game.user.targets=new Set([target]);const r=results();
await Promise.all([onUse(a,{},r),onUse(a,{},r)]);assert.equal(events.length,1);assert.deepEqual(events[0].to,{x:800,y:100});
const [auuid,arow]=areas[0];const area=activity(auuid,Object.keys(arow.activities)[0]);
game.user.targets=new Set([target,{center:{x:900,y:100}}]);
await onUse(area,{},results([{x:450,y:500,parent:{id:'scene'}}]));
assert.equal(events.length,2);assert.deepEqual(events[1].to,{x:450,y:500});
const error=console.error;console.error=()=>{};
await onUse(area,{},results([]));assert.equal(events.length,2);assert.ok(warnings.length);
console.error=error;
await onUse(a,{},{});await onUse(a,{}, {message:{uuid:'foreign',author:{id:'other'}}});assert.equal(events.length,2);
enabled=false;await onUse(a,{},results());enabled=true;
game.modules.get('sequencer').active=false;await onUse(a,{},results());game.modules.get('sequencer').active=true;assert.equal(events.length,2);
// Embedded item from an older imported summon: recover via the actor source UUID.
const embedded=Object.keys(BINDINGS).find(x=>x.includes('.Actor.'));const parent=embedded.split('.Item.')[0];
const old=activity(embedded,Object.keys(BINDINGS[embedded].activities)[0]);delete old.item._stats;
old.item.actor={_stats:{compendiumSource:parent}};assert.ok(visualFor(old));
// Canonical flags support detached/duplicated cards with renamed identifiers.
const bound={...a,item:{getFlag:(_s,k)=>k==='visuals'?{activities:{[aid]:row.activities[aid]}}:undefined}};
assert.ok(visualFor(bound));bound.item.getFlag=()=>({disabled:true});assert.equal(visualFor(bound),null);
// Same identifier from another module must never inherit a visual.
const unrelated={...a,item:{system:{identifier:row.identifier},_stats:{compendiumSource:'Compendium.other.spells.Item.same'},getFlag:()=>undefined}};
assert.equal(visualFor(unrelated),null);
console.log('144 bindings, old imports, template endpoint, repeat suppression and opt-out passed; mocked APIs only.');

// Healing appears on recipients, including the caster, with no flight/stretched geometry.
const healEntry=Object.entries(BINDINGS).find(([,r])=>r.identifier==='priest-cure-wounds');
const heal=activity(healEntry[0],'dnd5eactivity000');
let before=events.length;
game.user.targets=new Set([source]);await onUse(heal,{},results());
assert.equal(events.length,before+1);assert.deepEqual(events.at(-1).from,source.center);
assert.equal(events.at(-1).to,undefined);assert.equal(events.at(-1).file.endsWith('/holy-heal.webm'),true);
assert.ok(Math.abs(events.at(-1).size-220)<1e-6);assert.deepEqual(events.at(-1).anchor,{x:.5,y:.5});
const massEntry=Object.entries(BINDINGS).find(([,r])=>r.identifier==='druid-mass-healing-word');
const mass=activity(massEntry[0],'dnd5eactivity000');
const allies=Array.from({length:6},(_,i)=>({...target,center:{x:300+i*100,y:200},document:{...target.document,uuid:'ally'+i}}));
game.user.targets=new Set(allies);before=events.length;const same=results();
await Promise.all([onUse(mass,{},same),onUse(mass,{},same)]);
assert.equal(events.length,before+6);
for(const e of events.slice(before))assert.ok(e.file.endsWith('/nature-heal.webm'));
assert.deepEqual(events.slice(before).map(e=>e.from),allies.map(t=>t.center));
// Limits and invalid scenes are checked before playing any partial group.
console.error=()=>{};
for(const targets of [[],[...allies,target]]){
 game.user.targets=new Set(targets);before=events.length;await onUse(mass,{},results());assert.equal(events.length,before);
}
game.user.targets=new Set([allies[0],{...target,document:{...target.document,parent:{id:'elsewhere'}}}]);
before=events.length;await onUse(mass,{},results());assert.equal(events.length,before);
game.user.targets=new Set([allies[0],allies[1]]);
before=events.length;await onUse(heal,{},results());assert.equal(events.length,before);
console.error=error;
// Explicit self-heal ignores unrelated targets and requires no template or target selection.
const selfEntry=Object.entries(BINDINGS).find(([,r])=>r.identifier==='paladin-light-of-the-protector');
game.user.targets=new Set([target]);before=events.length;
await onUse(activity(selfEntry[0],'dnd5eactivity000'),{},results());
assert.equal(events.length,before+1);assert.deepEqual(events.at(-1).from,source.center);
// Only healing variants of Atonement, not its three damage choices or Lay on Hands cleanse.
const atone=Object.entries(BINDINGS).find(([,r])=>r.identifier==='priest-atonement');
assert.equal(Object.keys(atone[1].activities).length,9);
for(const id of ['dnd5eactivity001','dnd5eactivity002','dnd5eactivity003'])assert.equal(visualFor({...activity(atone[0],'dnd5eactivity000'),id,type:'damage'}),null);
const hands=Object.entries(BINDINGS).find(([,r])=>r.identifier==='paladin-lay-on-hands');
assert.equal(visualFor({...activity(hands[0],'dnd5eactivity000'),id:'dnd5eactivity001',type:'utility'}),null);
console.log('36 healing bindings: six recipients, caster target, self-heal, limits, invalid scene, duplicate uses and excluded follow-ups passed.');

// Each new flight uses its own media; the registry also serves old imports.
for (const profile of ['frost','shadow','fel']) {
 const entry=Object.entries(BINDINGS).find(([,r])=>Object.values(r.activities).some(x=>x.profile===`wow.${profile}.projectile`));
 const [u,r]=entry;const id=Object.keys(r.activities).find(k=>r.activities[k].profile===`wow.${profile}.projectile`);
 game.user.targets=new Set([target]);await onUse(activity(u,id),{},results());
 assert.ok(events.at(-1).file.endsWith(`/${profile}-projectile.webm`));
}
for (const r of Object.values(BINDINGS).filter(r=>['death-knight-shadow-bolt','warlock-shadow-bolt'].includes(r.identifier))) {
 assert.deepEqual(Object.keys(r.activities),['dnd5eactivity000']);
}
const orb=Object.values(BINDINGS).find(r=>r.identifier==='library-chromatic-orb');
assert.equal(orb.activities['49e221154a6b3b8d'].profile,'wow.fire.projectile');
assert.equal(orb.activities['c25ca9ec0e838f32'].profile,'wow.frost.projectile');
assert.equal(Object.keys(orb.activities).length,2);
for (const ident of ['chapter-frostfire-bolt','mage-frostfire-bolt','warlock-chaos-bolt','library-scorching-ray']) {
 assert.equal(Object.values(BINDINGS).some(r=>r.identifier===ident),false);
}

// Beam geometry uses the actual 3.6.11 stretch contract: size() is ignored
// on stretch effects, so Y scale is explicit and independent of distance.
for (const profile of ['frost','shadow','nature','drain']) {
 const [u,r]=Object.entries(BINDINGS).find(([,r])=>Object.values(r.activities).some(x=>x.profile===`wow.${profile}.beam`));
 const id=Object.keys(r.activities).find(k=>r.activities[k].profile===`wow.${profile}.beam`);
 game.user.targets=new Set([target]);await onUse(activity(u,id),{},results());
 const row=events.at(-1);assert.ok(row.file.endsWith(`/${profile}-beam.webm`));
 assert.deepEqual(row.stretch,{onlyX:true,cacheLocation:true});assert.deepEqual(row.template,{gridSize:128,startPoint:0,endPoint:0});
 assert.deepEqual(row.scale,{x:1,y:90/128});
 const scale=row.scale;target.center.x=1800;await onUse(activity(u,id),{},results());assert.deepEqual(events.at(-1).scale,scale);target.center.x=800;
}
for (const [u,r] of Object.entries(BINDINGS).filter(([,r])=>r.identifier.includes('mind-flay'))) {
 assert.deepEqual(Object.keys(r.activities),['dnd5eactivity000']);
 assert.equal(visualFor({...activity(u,'dnd5eactivity000'),id:'dnd5eactivity001'}),null);
}
for (const [u,r] of Object.entries(BINDINGS).filter(([,r])=>['warlock-drain-life','chapter-drain-life'].includes(r.identifier))) {
 const a=activity(u,'dnd5eactivity001');assert.equal(a.type,'damage');const n=events.length;await onUse(a,{},results());assert.equal(events.length,n+1);
 assert.equal(visualFor({...a,id:'dnd5eactivity002',type:'utility'}),null);
}
console.log('Beam-only stretch, distance-independent thickness, drain upkeep and no save/heal repeats passed.');
