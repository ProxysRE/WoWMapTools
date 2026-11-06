import assert from "node:assert/strict";
import {play, bind, onUse, visualFor, sourceFor} from "../foundry_modules/wowmap-effects/effects.mjs";

const calls=[];
globalThis.Sequence=class {
  constructor(){this.row=[];calls.push(this.row);}
  effect(){return this;}
  file(...x){this.row.push(['file',...x]);return this;}
  atLocation(...x){this.row.push(['from',...x]);return this;}
  moveTowards(...x){this.row.push(['to',...x]);return this;}
  moveSpeed(...x){this.row.push(['speed',...x]);return this;}
  duration(...x){this.row.push(['duration',...x]);return this;}
  size(...x){this.row.push(['size',...x]);return this;}
  spriteAnchor(...x){this.row.push(['anchor',...x]);return this;}
  fadeIn(){return this;}
  fadeOut(){return this;}
  async play(){this.row.push(['play']);}
};
let automatic=true;
const warnings=[];
globalThis.ui={notifications:{warn:x=>warnings.push(x)}};
globalThis.game={release:{generation:13},system:{id:'dnd5e',version:'5.3.3'},
  user:{id:'u1',isGM:false,targets:new Set()},modules:new Map([['sequencer',{active:true}]]),settings:{get:()=>automatic}};
const actor={uuid:'Actor.1'};
function token(id,x){return {actor,controlled:false,center:{x,y:50},isVisible:true,document:{uuid:'Scene.s.Token.'+id,parent:{id:'s'},isOwner:true}};}
const source=token('source',50),target=token('target',850);
globalThis.canvas={ready:true,scene:{id:'s'},grid:{size:100},tokens:{placeables:[source],controlled:[source]}};
let flags={};
const item={actor,isOwner:true,system:{activities:new Map([['a',{}],['b',{}]])},getFlag:()=>flags,async setFlag(_s,_k,v){flags=v;}};
const activity={id:'a',actor,item};
await bind(item,'a');assert.equal(visualFor(activity),'wow.fire.projectile');assert.equal(visualFor({...activity,id:'b'}),null);
const result=await play({source,target});assert.equal(result.duration,1000);
assert.deepEqual(calls[0].find(x=>x[0]==='from')[1],{x:50,y:50});
assert.deepEqual(calls[0].find(x=>x[0]==='to')[1],{x:850,y:50});
assert.equal(calls[0].filter(x=>x[0]==='play').length,1);
game.user.targets=new Set([target]);
const message={uuid:'ChatMessage.1',author:{id:'u1'}};
await Promise.all([onUse(activity,{}, {message}),onUse(activity,{}, {message})]);
assert.equal(calls.length,2,'same use broadcasts only once');
await onUse(activity,{}, {message:{uuid:'other-user',author:{id:'u2'}}});
await onUse(activity,{}, {});await onUse({...activity,id:'b'},{},{message:{...message,uuid:'unbound'}});
automatic=false;await onUse(activity,{},{message:{...message,uuid:'disabled'}});automatic=true;
assert.equal(calls.length,2,'other users, no message, unbound and disabled do not play');
await bind(item,'a',null);assert.equal(visualFor(activity),null);await bind(item,'a');
await assert.rejects(bind(item,'missing'));await assert.rejects(bind(item,'a','untrusted-file'));
const other=token('other',150);canvas.tokens.placeables.push(other);assert.throws(()=>sourceFor(actor),/Выберите/);
source.controlled=true;assert.equal(sourceFor(actor),source);canvas.tokens.placeables.pop();
await assert.rejects(play({source,target:source}),/другой токен/);
target.document.parent.id='other';await assert.rejects(play({source,target}),/текущей сцены/);target.document.parent.id='s';
source.document.isOwner=false;await assert.rejects(play({source,target}),/владение/);source.document.isOwner=true;
target.isVisible=false;await assert.rejects(play({source,target}),/просмотра/);target.isVisible=true;
game.modules.get('sequencer').active=false;await assert.rejects(play({source,target}),/Sequencer/);game.modules.get('sequencer').active=true;
assert.equal(calls.length,2,'all failed preflights leave playback unchanged');
assert.equal(warnings.length,0);
console.log('Effect adapter checks passed (mock API; no in-game verification).');
