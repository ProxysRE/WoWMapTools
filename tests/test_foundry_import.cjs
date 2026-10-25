// Workflow tests with a fake Foundry API. These do not replace testing in Foundry.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const code = fs.readFileSync(require('node:path').join(__dirname,'../wowmap/import_foundry.js'),'utf8');
async function test({collision=false, missing=false, invalid=false, generation=13}={}) {
  const errors=[];const calls=[];
  const doc={_id:'sceneId',name:'Inn',background:{src:'wowmap/inn/ground/background.webp'},tiles:[],regions:[]};
  class Scene {
    constructor(data){this.regions=[];if(invalid)throw Error('invalid schema');}
    validate(){return true;}
    static async createDocuments(data,options){calls.push({data,options});return data;}
  }
  const context={game:{user:{isGM:true},release:{generation},scenes:{has:()=>collision}},
    foundry:{applications:{api:{DialogV2:{prompt:async()=> 'custom/inn/bundle.json'}}},utils:{deepClone:structuredClone}},
    CONFIG:{Scene:{documentClass:Scene},RegionBehavior:{dataModels:{}}},
    fetch:async(url,opts)=> opts?.method==='HEAD'? {ok:!missing,status:404}:
      {ok:true,json:async()=>({format:'wowmap.foundry/1',mediaRoot:'wowmap/inn',scenes:[doc]})},
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
  console.log('Foundry importer workflow checks passed (mock API)');
})().catch(error=>{console.error(error);process.exitCode=1});
