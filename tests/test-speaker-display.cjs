// Run with Playwright available on NODE_PATH. Uses the actual display functions.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const source = fs.readFileSync(path.join(__dirname, '../app/static/app.js'), 'utf8');
function extract(name) {
  let start = source.indexOf(`function ${name}(`);
  if (source.slice(start - 6, start) === 'async ') start -= 6;
  return source.slice(start, source.indexOf('\n}', start) + 2);
}
(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || undefined});
  try {
    const page = await browser.newPage();
    await page.route('http://frivo.test/**', route => route.fulfill({contentType: 'text/html', body:
      '<div id="listenLog"></div><div id="listenPeopleCount"></div><textarea id="messageInput"></textarea>'}));
    await page.goto('http://frivo.test');
    await page.addScriptTag({content: `
      const listenLog = document.getElementById('listenLog');
      const listenPeopleCount = document.getElementById('listenPeopleCount');
      const messageInput = document.getElementById('messageInput');
      let SPEAKER_NAMES_KEY = 'session-one', listenEntrySeq = 0, activeListenSession = null;
      const IS_APPLE = false;
      const listenIsAtBottom = () => true, listenKeepPinned = () => {}, speakerColor = () => '#4fc3f7';
      const applySpeakerMerges = () => {}, renameSpeaker = () => {}, resetLiveDictation = () => {};
      const listenTargetLanguage = () => 'English', setListenStatus = () => {}, friendlyListenError = String;
      ${['speakerNames','speakerLabel','updateSpeakerCount','addListenEntry','applySpeakerGrouping',
         'fillListenEntry','ensureListenNode','sendListenSegment','deliverListenSegment'].map(extract).join('\n')}
    `});
    const result = await page.evaluate(async () => {
      const segments = [
        {text:'Hello', speaker:{id:1,name:'Alice',confirmed:true}, source:'clean'},
        {text:'Good morning', speaker:{id:2,confirmed:true}, source:'separated',overlapping:true},
        {text:'Unclear',speaker:null,source:'overlap',overlapping:true},
        {text:'New person',speaker:{id:3,confirmed:false},source:'clean'},
        {text:'Tracked overlap',speaker:null,voice_track:{id:'session-track-1',label:'Voice track 1',verified:false},source:'separated'},
      ];
      window.fetch = async () => ({ok:true,json:async()=>({text:'all',segments,speaker_status:{state:'ready'}})});
      const owner = {sessionId:'test',pending:Promise.resolve()}; activeListenSession=owner;
      const ref = {node:null,owner};
      await sendListenSegment([], 'audio/webm', ref, false);
      const labels = [...document.querySelectorAll('.listen-speaker')].map(e=>e.textContent);
      const text = [...document.querySelectorAll('.listen-text')].map(e=>e.textContent);
      // An old partial must never append or overwrite the finalized rows.
      await sendListenSegment([], 'audio/webm', ref, true);
      return {labels,text,count:document.querySelectorAll('.listen-entry').length,
              people:listenPeopleCount.textContent,done:ref.done};
    });
    assert.deepEqual(result.labels, ['Alice','Speaker 2 · overlap (unverified)',
      'Overlapping voices · unidentified','Speaker 3 · learning','Voice track 1 · unverified']);
    assert.deepEqual(result.text, ['Hello','Good morning','Unclear','New person','Tracked overlap']);
    assert.equal(result.count,5); assert.equal(result.people,'3 people · 1 unverified track'); assert.equal(result.done,true);
    console.log('Browser: separate speaker rows, saved names, overlap warnings, learning labels, late partial protection passed.');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
