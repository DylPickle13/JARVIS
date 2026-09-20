// Experimental local-only D100C adapter. No automatic retries or arbitrary RPC.
import fs from 'node:fs';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {runtimeDigest} from './security_chime_integrity.mjs';

const root = new URL('.', import.meta.url);
const dependency = new URL('private-notes/chime-tpap-v2/', root);
const cipherUrl = new URL('security_chime_transport.mjs', root);
const cipherHash = 'ed99b90525c77718e6f83e8b432e30345d22c4419fa0976b3c5cc9adf536fada';
let session;
let actionStarted = false;
let operation = 'unknown';
const deadline = setTimeout(() => {
 console.log(JSON.stringify({result:'error',reason:actionStarted?'chime_action_outcome_unknown':'chime_timeout'}));
 process.exit(2);
}, 25000);
function fail(reason) { throw new Error(reason); }
function scalar(value) {
 return typeof value==='string' && /^[A-Za-z0-9 ._()-]{1,64}$/.test(value) ? value : null;
}
try {
 const input = JSON.parse(fs.readFileSync(0,'utf8'));
 operation=input.operation;
 if (!['status','capabilities','ring','stop'].includes(operation)) fail('unsupported_chime_command');
 if (['ring','stop'].includes(operation) && input.confirm!==true) fail('confirmation_required');
 if (operation==='ring' && (!/^[1-6]$/.test(input.tone) || !Number.isInteger(input.volume) || input.volume<1 || input.volume>3 ||
     !Number.isInteger(input.seconds) || input.seconds<1 || input.seconds>5)) fail('invalid_chime_ring');
 if (!/^192\.168\.\d{1,3}\.\d{1,3}$/.test(input.host) || !input.username || !input.password) fail('invalid_chime_input');
 if (crypto.createHash('sha256').update(fs.readFileSync(cipherUrl)).digest('hex')!==cipherHash) fail('chime_transport_integrity_failed');
 if(runtimeDigest(fileURLToPath(new URL('node_modules/',dependency)))!==
    'f39caf5cd8eda71b5b6c74abe8b2b630b6f9ac68f382ea3dfc1c9909f0d7666b') fail('chime_transport_integrity_failed');
 const {default:TpapSession}=await import(cipherUrl.href);
 session=new TpapSession({host:input.host,password:input.password,maxRequests:operation==='ring'?7:6});
 input.password='';
 await session.handshake();
 const query=(method,params={})=>session.query(method,params);
 const info=await query('get_device_info');
 if(typeof info?.model!=='string' || info.model.split('(')[0]!=='D100C') fail('device_identity_mismatch');
 const result={result:'read_succeeded',model:'D100C',authenticated:true,
  hardware:scalar(info.hw_ver),firmware:scalar(info.fw_ver),transport:'tpap_experimental',
  custom_audio:{supported_in_cli:false,device_support:'not_verified',upload_or_stream_endpoint:'not_found'},
  physical_verification:'not_assessed'};
 if(operation==='stop') {
  actionStarted=true;
  await query('stop_alarm');
  console.log(JSON.stringify({...result,result:'chime_stop_acknowledged'}));
 } else {
  const tones=await query('get_support_alarm_type_list');
  if(!Array.isArray(tones?.alarm_type_list) || tones.alarm_type_list.length>32 ||
     !tones.alarm_type_list.every(t=>typeof t==='string'&&/^[1-6]$/.test(t))) fail('chime_tones_unavailable');
  const config=await query('get_alarm_configure');
  if(!config || typeof config!=='object' || Array.isArray(config)) fail('chime_config_unavailable');
  result.tones=[...new Set(tones.alarm_type_list)];
  function cleanConfig(value) {
   if(!value || !result.tones.includes(value.type) || !['mute','low','normal','high'].includes(value.volume) ||
      !Number.isInteger(value.duration) || value.duration<1 || value.duration>600) fail('chime_config_unavailable');
   return {type:value.type,volume:value.volume,duration:value.duration};
  }
  result.reported_config=cleanConfig(config);
  if(operation==='ring') {
   if(!result.tones.includes(input.tone) || !['type','volume','duration'].every(k=>Object.hasOwn(result.reported_config,k))) fail('chime_ring_preflight_failed');
   actionStarted=true;
   await query('play_alarm',{alarm_type:input.tone,
    alarm_volume:['mute','low','normal','high'][input.volume],alarm_duration:input.seconds});
   const after=cleanConfig(await query('get_alarm_configure'));
   const unchanged=JSON.stringify(after)===JSON.stringify(result.reported_config);
   console.log(JSON.stringify({...result,result:'chime_ring_acknowledged',requested_seconds:input.seconds,
    control_verification:'pending_owner_test',persistent_settings_write_sent:false,
    persistent_settings_unchanged:unchanged,settings_readback:after}));
  } else {
   const components=await query('component_nego');
   result.advertised_components=(components?.component_list??[]).map(c=>c.id).filter(c=>typeof c==='string'&&/^[a-z0-9_]{1,48}$/.test(c)).slice(0,64);
   console.log(JSON.stringify(result));
  }
 }
} catch(error) {
 const known=new Set(['unsupported_chime_command','confirmation_required','invalid_chime_ring','invalid_chime_input',
  'chime_transport_integrity_failed','chime_request_not_allowed','chime_response_sequence_mismatch','chime_request_rejected',
  'device_identity_mismatch','chime_tones_unavailable','chime_config_unavailable','chime_ring_preflight_failed']);
 const reason=actionStarted?'chime_action_outcome_unknown':known.has(error.message)?error.message:'chime_read_failed';
 console.log(JSON.stringify({result:'error',reason}));process.exitCode=2;
} finally {session?.close();clearTimeout(deadline);}
