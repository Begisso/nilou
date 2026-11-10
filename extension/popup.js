const $ = (id) => document.getElementById(id);

async function init() {
  const settings = await nilouSettings();
  $('enabled').checked = settings.enabled;
  $('port').value = settings.port;
  $('minSize').value = settings.minSizeKB;

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const alive = await callNilou('/ping', null, 2000);
  $('status').textContent = alive ? `Connected · Nilou ${alive.version}` : 'Nilou is not running — start Nilou.exe';
  $('status').className = 'status ' + (alive ? 'ok' : 'bad');
  $('grab').disabled = !alive || !tab || !/^https?:/i.test(tab.url || '');

  if (alive && tab && VIDEO_SITE.test(tab.url || '')) {
    $('video').hidden = false;
    $('video').textContent = /youtu/i.test(tab.url) ? 'Download this YouTube video'
      : /(^|\.)(x|twitter)\.com/i.test(new URL(tab.url).hostname) ? 'Download this X video' : 'Download this video';
  }

  $('video').onclick = async () => {
    $('note').textContent = 'Sending to Nilou…';
    const ok = await sendVideo(tab.url, tab.url);
    $('note').textContent = ok ? 'Opened in Nilou — pick a quality there.' : 'Could not reach Nilou.';
    if (ok) setTimeout(() => window.close(), 900);
  };
  $('grab').onclick = async () => {
    $('note').textContent = 'Scanning the page…';
    const res = await grabTab(tab);
    $('note').textContent = res.ok ? `Found ${res.count} items — choose them in Nilou.` : res.error;
    if (res.ok) setTimeout(() => window.close(), 900);
  };
  $('enabled').onchange = () => chrome.storage.local.set({ enabled: $('enabled').checked });
  $('port').onchange = () => {
    const port = parseInt($('port').value, 10);
    if (port >= 1024 && port <= 65535) chrome.storage.local.set({ port });
  };
  $('minSize').onchange = () => chrome.storage.local.set({ minSizeKB: Math.max(0, parseInt($('minSize').value, 10) || 0) });
}

init();
