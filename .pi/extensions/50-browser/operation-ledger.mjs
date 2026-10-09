import { mkdir, lstat, open } from 'node:fs/promises';
import { constants } from 'node:fs';
import { dirname } from 'node:path';
import { randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { createInterface } from 'node:readline';

const ACTIONS = new Set(['/connect','/prepare-anchor','/status','/tabs','/type','/click','/key','/scroll','/upload','/open','/new-tab','/extract','/screenshot','/wait','/close']);
const STATES = new Set(['executing','draining','blocked','resolved']);
const FIELDS = ['id','action','sessionId','tabId','windowId','generation','state','revision','persistedRevision','requestEntered','requestTerminal','snippetEntered','snippetTerminal','outcome','valueVerified','resultTabId','pending','unknown'];
function clean(record) { return Object.fromEntries(FIELDS.map(k=>[k,record[k]])); }
function valid(r) {
  return r && /^[a-f0-9-]{36}:\d+$/.test(r.id) && ACTIONS.has(r.action) && STATES.has(r.state) &&
    (r.sessionId === null || (typeof r.sessionId === 'string' && /^[a-zA-Z0-9_-]{1,128}$/.test(r.sessionId))) &&
    ['tabId','windowId','resultTabId'].every(k=>r[k]===null || (Number.isSafeInteger(r[k])&&r[k]>0)) &&
    ['generation','revision','persistedRevision','pending'].every(k=>Number.isSafeInteger(r[k])&&r[k]>=0) &&
    ['requestEntered','requestTerminal','snippetEntered','snippetTerminal','valueVerified','unknown'].every(k=>typeof r[k]==='boolean') &&
    ['pending','completed','failed'].includes(r.outcome) && (r.state!=='resolved' ||
      (r.requestEntered&&r.requestTerminal&&r.snippetEntered&&r.snippetTerminal&&
       r.pending===0&&!r.unknown&&r.persistedRevision===r.revision&&r.outcome!=='pending'));
}

export class OperationLedger {
  constructor({path=null, historyLimit=64}={}) {
    this.path=path;this.historyLimit=historyLimit;this.boot=randomUUID();this.sequence=0;
    this.records=new Map();this.writes=Promise.resolve();this.error=false;this.loaded=false;
    this.lockProcess=null;this.reply=null;this.writeSequence=0;
  }
  async load() {
    if(this.loaded) return;
    if(this.path) {
      const directory=dirname(this.path);
      await mkdir(directory,{recursive:true,mode:0o700});
      const d=await lstat(directory);
      if(!d.isDirectory()||d.uid!==process.getuid()||(d.mode&0o777)!==0o700) throw new Error('Unsafe browser recovery journal directory');
      try {
        const file=await open(this.path,constants.O_RDONLY|constants.O_NOFOLLOW);
        try {
          const s=await file.stat();
          if(!s.isFile()||s.uid!==process.getuid()||(s.mode&0o777)!==0o600||s.size>1024*1024) throw new Error('Unsafe browser recovery journal');
          const data=JSON.parse(await file.readFile('utf8'));
          if(data.version!==1||!Array.isArray(data.records)||data.records.length>1024||data.records.some(r=>!valid(r))||new Set(data.records.map(r=>r.id)).size!==data.records.length) throw new Error('Invalid browser recovery journal');
          for(const r of data.records) this.records.set(r.id,clean(r));
        } finally {await file.close();}
      } catch(error) {if(error.code!=='ENOENT') throw new Error('Browser recovery journal unavailable or invalid',{cause:error});}
    }
    this.loaded=true;
  }
  async acquireLock() {
    if(!this.path||this.lockProcess) return;
    const child=spawn('/usr/bin/python3',[fileURLToPath(new URL('./lock-operation-journal.py',import.meta.url)),this.path],{stdio:['pipe','pipe','ignore']});
    this.lockProcess=child;this.writeSequence=0;
    const ready=this.expectReply('locked');
    const lines=createInterface({input:child.stdout});
    lines.on('line',line=>{
      if(!this.reply||line!==this.reply.expected) {this.reply?.reject();this.error=true;child.kill();return;}
      this.reply.resolve();
    });
    const failed=()=>{this.reply?.reject();if(this.lockProcess===child)this.error=true;};
    child.on('error',failed);child.once('exit',failed);child.stdin.on('error',failed);
    try {
      await ready;
      child.unref();child.stdin.unref?.();child.stdout.unref?.();
      // A readonly startup snapshot may predate another writer's activity.
      // Reload under the acquired kernel lock before authorizing any dispatch.
      this.records.clear();this.loaded=false;await this.load();
    } catch(error) {this.error=true;throw error;}
  }
  expectReply(expected) {
    return new Promise((resolve,reject)=>{
      const entry={expected,resolve:()=>{clearTimeout(timer);if(this.reply===entry)this.reply=null;resolve();},
        reject:()=>{clearTimeout(timer);if(this.reply===entry)this.reply=null;this.error=true;reject(new Error('Browser journal writer unavailable or unsafe'));}};
      const timer=setTimeout(entry.reject,3000);this.reply=entry;
    });
  }
  async writeJournal(body) {
    if(!this.lockProcess||this.error) throw new Error('Browser journal writer unavailable');
    const sequence=++this.writeSequence;
    const written=this.expectReply('written:'+sequence);
    this.lockProcess.stdin.write(JSON.stringify({sequence,body})+'\n');
    await written;
  }
  async close() {
    const child=this.lockProcess;this.lockProcess=null;
    if(!child) return;
    await new Promise(resolve=>{
      const timer=setTimeout(()=>{child.kill();resolve();},1000);timer.unref?.();
      child.once('exit',()=>{clearTimeout(timer);resolve();});child.stdin.end();
      if(child.exitCode!==null||child.signalCode!==null) {clearTimeout(timer);resolve();}
    });
  }
  unresolved() {return [...this.records.values()].filter(r=>r.state!=='resolved').map(clean);}
  async begin({action,sessionId=null,tabId=null,windowId=null,generation=0}) {
    await this.load();
    if(this.error||this.unresolved().length) throw new Error('Unresolved recovery evidence prevents dispatch');
    await this.acquireLock();
    if(this.error||this.unresolved().length) throw new Error('Unresolved recovery evidence prevents dispatch');
    const r={id:`${this.boot}:${++this.sequence}`,action,sessionId,tabId,windowId,generation,
      state:'executing',revision:0,persistedRevision:0,requestEntered:false,requestTerminal:false,
      snippetEntered:false,snippetTerminal:false,outcome:'pending',valueVerified:false,resultTabId:null,pending:0,unknown:false};
    if(!valid(r)) throw new Error('Invalid browser operation metadata');
    this.records.set(r.id,r);await this.save();return r;
  }
  receipt(r, s) {
    if(this.records.get(r.id)!==r||s.id!==r.id||s.revision<=r.revision) return Promise.resolve();
    for(const key of ['revision','requestEntered','requestTerminal','snippetEntered','snippetTerminal','outcome','valueVerified','resultTabId','pending']) r[key]=s[key];
    r.unknown ||= s.unknown;
    if(!valid(r)) {this.error=true;return Promise.reject(new Error('Invalid execution receipt'));}
    // The initial durable 'executing' record already fences every crash. Keep
    // high-frequency command counters in memory; fsync terminal proof/state,
    // not every keyboard/CDP round trip. This avoids turning recovery telemetry
    // into thousands of full-journal writes during ordinary typing.
    return r.requestTerminal&&r.snippetTerminal&&r.pending===0&&!r.unknown ? this.save() : Promise.resolve();
  }
  async state(r,state) {
    if(!STATES.has(state)||this.records.get(r.id)!==r) throw new Error('Invalid operation state');
    if(state==='resolved'&&!this.proven(r)) throw new Error('Execution proof required before resolving journal');
    r.state=state;await this.save();
  }
  proven(r) {
    return !this.error&&this.records.get(r.id)===r&&r.persistedRevision===r.revision&&
      r.requestEntered&&r.requestTerminal&&r.snippetEntered&&r.snippetTerminal&&r.pending===0&&!r.unknown;
  }
  async flush() {await this.writes;if(this.error)throw new Error('Browser recovery journal write failed');}
  save() {
    // Serialize NOW, not after the write queue advances. Persisting an older
    // snapshot cannot accidentally certify a newer receipt revision.
    const revisions=[...this.records.values()].map(r=>[r,r.revision]);
    const resolved=[...this.records.values()].filter(r=>r.state==='resolved');
    for(const r of resolved.slice(0,Math.max(0,resolved.length-this.historyLimit))) this.records.delete(r.id);
    const body=JSON.stringify({version:1,records:[...this.records.values()].map(r=>({...clean(r),persistedRevision:r.revision}))});
    const write=async()=>{
      if(this.error) throw new Error('Browser recovery journal write failed');
      if(this.path) await this.writeJournal(body);
      for(const [r,revision] of revisions) r.persistedRevision=Math.max(r.persistedRevision,revision);
    };
    const result=this.writes.then(write);
    this.writes=result.catch(()=>{this.error=true;});
    return result;
  }
  summaries(sessionId) {
    return [...this.records.values()].filter(r=>r.sessionId===sessionId&&r.state!=='executing').slice(-8)
      .map(r=>({operationId:r.id,action:r.action,outcome:r.outcome,state:r.state,valueVerified:r.valueVerified}));
  }
}
