// Workflow tests with a fake Foundry API; not a substitute for an in-game test.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const code = fs.readFileSync(require('node:path').join(__dirname,'../wowmap/import_foundry.js'),'utf8');
async function test({collision=false, missing=false, invalid=false, generation=13,
                     populated=false, actorCollision=false, invalidActor=false, missingNested=false, systemVersion='5.3.3', delta}={}) {
  const errors=[];const calls=[];const existingActors=new Set();
  const doc={_id:'sceneId',name:'Inn',background:{src:'wowmap/inn/ground/background.webp'},tiles:[],regions:[],
    tokens:populated?[{name:'Innkeeper',actorId:'actorId',texture:{src:'icons/svg/mystery-man.svg'}}]:[]};
  if (populated && delta !== undefined) doc.tokens[0].delta = structuredClone(delta);
  const actors=populated?[{_id:'actorId',name:'Innkeeper',type:'npc',img:'icons/svg/mystery-man.svg',
    items:[{name:'Key',img:'wowmap/content/icons/test.webp'}]}]:[];
  class Actor {
    constructor(){if(invalidActor)throw Error('invalid actor schema');}
    validate(){return true;}
    static async createDocuments(data,options){calls.push({kind:'actors',data,options});for(const a of data)existingActors.add(a._id);return data;}
  }
  class Scene {
    constructor(data){
      this.regions=[];if(invalid)throw Error('invalid scene schema');
      for(const t of data.tokens || []) {
        const d=t.delta;
        if(!d || typeof d.system!=='object' || !Array.isArray(d.items) || !Array.isArray(d.effects) || typeof d.flags!=='object')
          throw Error('delta: system/items/effects/flags may not be undefined');
      }
    }
    validate(){return true;}
    static async createDocuments(data,options){
      for(const s of data)for(const t of s.tokens||[])assert.equal(existingActors.has(t.actorId),true,'Actors must precede linked tokens');
      calls.push({kind:'scenes',data,options});return data;
    }
  }
  const context={game:{user:{isGM:true},release:{generation},system:{id:'dnd5e',version:systemVersion},
      scenes:{has:()=>collision},actors:{has:id=>actorCollision||existingActors.has(id)}},
    foundry:{applications:{api:{DialogV2:{prompt:async()=> 'custom/inn/bundle.json'}}},utils:{deepClone:structuredClone}},
    CONFIG:{Scene:{documentClass:Scene},Actor:{documentClass:Actor},RegionBehavior:{dataModels:{}}},
    fetch:async(url,opts)=> opts?.method==='HEAD'? {ok:!missing&&!(missingNested&&url==='wowmap/content/icons/test.webp'),status:404}:
      {ok:true,json:async()=>({format:'wowmap.foundry/1',mediaRoot:'wowmap/inn',scenes:[doc],actors,targets:{dnd5e:'5.3.3'}})},
    ui:{notifications:{error:msg=>errors.push(msg),info:()=>{}}},console:{error:()=>{}}};
  await vm.runInNewContext(code,context);
  return {calls,errors};
}
(async()=>{
  const success=await test();assert.equal(success.errors.length,0);assert.equal(success.calls.length,1);
  assert.equal(success.calls[0].options.keepId,true);assert.equal(success.calls[0].options.keepEmbeddedIds,true);
  assert.equal(success.calls[0].data[0].background.src,'custom/inn/ground/background.webp');
  for(const options of [{collision:true},{missing:true},{invalid:true},{generation:14}]) {
    const result=await test(options);assert.equal(result.calls.length,0);assert.equal(result.errors.length,1);
  }
  const populated=await test({populated:true});assert.equal(populated.errors.length,0);
  assert.equal(populated.calls.length,2);assert.equal(populated.calls[0].kind,'actors');assert.equal(populated.calls[1].kind,'scenes');
  assert.equal(populated.calls[1].data[0].tokens[0].actorId,populated.calls[0].data[0]._id);
  assert.equal(populated.calls[0].options.keepId,true);assert.equal(populated.calls[0].options.keepEmbeddedIds,true);
  for (const delta of [{}, {system:{attributes:{hp:{value:7}}},items:[{_id:'item'}],effects:[],flags:{world:{test:true}}}]) {
    const result=await test({populated:true,delta});assert.equal(result.errors.length,0);
    const actual=result.calls[1].data[0].tokens[0].delta;
    assert.deepEqual(JSON.parse(JSON.stringify(actual)),{system:{},items:[],effects:[],flags:{},...delta});
  }
  const badDelta=await test({populated:true,delta:{items:'broken'}});
  assert.equal(badDelta.calls.length,0);assert.equal(badDelta.errors.length,1);
  for(const options of [{actorCollision:true},{invalidActor:true},{missing:true},{missingNested:true},{systemVersion:'4.0.0'}]) {
    const result=await test({populated:true,...options});assert.equal(result.calls.length,0);assert.equal(result.errors.length,1);
  }
  console.log('Foundry importer workflow checks passed (mock API, maps and populations)');
})().catch(error=>{console.error(error);process.exitCode=1});
