importScripts('shared.js');

const MENU = {
  link: 'nilou-link',
  media: 'nilou-media',
  video: 'nilou-video',
  grab: 'nilou-grab',
};

function setupMenus() {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: MENU.link, title: 'Download with Nilou', contexts: ['link'] });
    chrome.contextMenus.create({ id: MENU.media, title: 'Download this %s with Nilou', contexts: ['image', 'video', 'audio'] });
    chrome.contextMenus.create({ id: MENU.video, title: 'Download video from this page with Nilou', contexts: ['page', 'video', 'link'] });
    chrome.contextMenus.create({ id: MENU.grab, title: 'Grab media from this page with Nilou', contexts: ['page', 'image'] });
  });
}

async function flagError(text) {
  await chrome.action.setBadgeBackgroundColor({ color: '#c42b1c' });
  await chrome.action.setBadgeText({ text: '!' });
  await chrome.action.setTitle({ title: `Nilou: ${text}` });
  setTimeout(() => {
    chrome.action.setBadgeText({ text: '' });
    chrome.action.setTitle({ title: 'Nilou' });
  }, 6000);
}

async function heartbeat() {
  const alive = await callNilou('/ping', null, 2000);
  await chrome.action.setBadgeText({ text: '' });
  await chrome.action.setTitle({ title: alive ? 'Nilou — connected' : 'Nilou — app not running' });
  return alive;
}

chrome.runtime.onInstalled.addListener(() => {
  setupMenus();
  chrome.alarms.create('nilou-heartbeat', { periodInMinutes: 1 });
  heartbeat();
});
chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create('nilou-heartbeat', { periodInMinutes: 1 });
  heartbeat();
});
chrome.alarms.onAlarm.addListener((a) => { if (a.name === 'nilou-heartbeat') heartbeat(); });

// Hand browser downloads over to Nilou.
chrome.downloads.onCreated.addListener(async (item) => {
  const settings = await nilouSettings();
  if (!settings.enabled || item.incognito || item.byExtensionId || item.state !== 'in_progress') return;
  const url = item.finalUrl || item.url;
  if (!/^https?:/i.test(url)) return;          // blob:, data: and file: stay in the browser
  const size = item.totalBytes || item.fileSize || 0;
  if (settings.minSizeKB > 0 && size > 0 && size < settings.minSizeKB * 1024) return;

  try { await chrome.downloads.pause(item.id); } catch (e) { /* may already be done */ }
  const [current] = await chrome.downloads.search({ id: item.id });
  if (current && current.state === 'complete') return;   // tiny file finished before we could pause it

  const name = (item.filename || '').split(/[\\/]/).pop();
  const ok = await callNilou('/download', {
    url,
    filename: name,
    referrer: item.referrer || '',
    mime: item.mime || '',
    size: size > 0 ? size : -1,
    userAgent: navigator.userAgent,
    cookies: await cookieHeader(url),
  });
  if (ok) {
    try { await chrome.downloads.cancel(item.id); } catch (e) {}
    try { await chrome.downloads.erase({ id: item.id }); } catch (e) {}
  } else {
    try { await chrome.downloads.resume(item.id); } catch (e) {}
  }
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  let ok = null;
  if (info.menuItemId === MENU.link || info.menuItemId === MENU.media) {
    const url = info.menuItemId === MENU.link ? info.linkUrl : info.srcUrl;
    if (!url || !/^https?:/i.test(url)) return flagError('this item cannot be downloaded directly');
    if (info.menuItemId === MENU.link && VIDEO_SITE.test(url)) {
      ok = await sendVideo(url, info.pageUrl);
    } else {
      ok = await callNilou('/download', {
        url, referrer: info.pageUrl || '', userAgent: navigator.userAgent, cookies: await cookieHeader(url), ask: true,
      });
    }
  } else if (info.menuItemId === MENU.video) {
    const url = (info.linkUrl && VIDEO_SITE.test(info.linkUrl)) ? info.linkUrl : (tab && tab.url) || info.pageUrl;
    ok = await sendVideo(url, info.pageUrl);
  } else if (info.menuItemId === MENU.grab && tab) {
    const res = await grabTab(tab);
    ok = res.ok;
    if (!ok) return flagError(res.error);
  }
  if (!ok) flagError('Nilou is not running');
});
