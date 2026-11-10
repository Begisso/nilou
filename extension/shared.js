// Shared between the service worker and the popup.
const NILOU_DEFAULTS = { enabled: true, port: 9614, minSizeKB: 0 };

const VIDEO_SITE = /^https?:\/\/([a-z0-9-]+\.)*(youtube\.com|youtu\.be|x\.com|twitter\.com|vimeo\.com|tiktok\.com|instagram\.com|facebook\.com|fb\.watch|reddit\.com|twitch\.tv|dailymotion\.com|soundcloud\.com|bilibili\.com|bsky\.app|threads\.net|threads\.com)(\/|$)/i;

async function nilouSettings() {
  return chrome.storage.local.get(NILOU_DEFAULTS);
}

async function callNilou(path, body, timeoutMs = 4000) {
  const { port } = await nilouSettings();
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`http://127.0.0.1:${port}${path}`, {
      method: body ? 'POST' : 'GET',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    });
    const data = await res.json().catch(() => null);
    return res.ok && data && data.ok ? data : null;
  } catch (e) {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

async function cookieHeader(url) {
  try {
    const cookies = await chrome.cookies.getAll({ url });
    return cookies.map((c) => `${c.name}=${c.value}`).join('; ');
  } catch (e) {
    return '';
  }
}

async function cookieList(url) {
  try {
    return (await chrome.cookies.getAll({ url })).map((c) => ({
      domain: c.domain, hostOnly: c.hostOnly, path: c.path, secure: c.secure,
      expirationDate: c.expirationDate || 0, name: c.name, value: c.value,
    }));
  } catch (e) {
    return [];
  }
}

// Runs inside the page: list images, video, audio and linked files.
function nilouCollectMedia() {
  const items = new Map();
  const fileExt = /\.(jpe?g|png|gif|webp|avif|bmp|svg|tiff?|ico|heic|mp4|m4v|mkv|webm|mov|avi|wmv|flv|mpe?g|3gp|ts|m3u8|mp3|m4a|aac|flac|wav|ogg|oga|opus|wma|pdf|docx?|xlsx?|pptx?|odt|ods|epub|zip|rar|7z|tar|gz|tgz|bz2|xz|iso|exe|msi|apk|dmg)(?:$|[?#])/i;
  const typeOf = (u, hint) => {
    const m = (u.split('?')[0].match(/\.([a-z0-9]+)$/i) || [])[1];
    if (!m) return hint;
    const e = m.toLowerCase();
    if (/^(jpe?g|png|gif|webp|avif|bmp|svg|tiff?|ico|heic)$/.test(e)) return 'image';
    if (/^(mp4|m4v|mkv|webm|mov|avi|wmv|flv|mpe?g|3gp|ts|m3u8)$/.test(e)) return 'video';
    if (/^(mp3|m4a|aac|flac|wav|ogg|oga|opus|wma)$/.test(e)) return 'audio';
    return hint || 'file';
  };
  const add = (raw, hint, extra) => {
    if (!raw) return;
    let url;
    try { url = new URL(raw, location.href).href; } catch (e) { return; }
    if (!/^https?:/i.test(url)) return;
    url = url.split('#')[0];
    if (items.has(url)) return;
    const name = decodeURIComponent((new URL(url).pathname.split('/').pop() || '')).slice(0, 200);
    items.set(url, Object.assign({ url, type: typeOf(url, hint), name }, extra || {}));
  };
  const largest = (srcset) => {
    let best = null, score = -1;
    (srcset || '').split(',').forEach((part) => {
      const [u, d] = part.trim().split(/\s+/);
      const v = parseFloat(d) || 1;
      if (u && v > score) { score = v; best = u; }
    });
    return best;
  };
  document.querySelectorAll('img').forEach((img) => {
    const src = largest(img.srcset) || img.currentSrc || img.src || img.dataset.src;
    add(src, 'image', { w: img.naturalWidth || img.width || 0, h: img.naturalHeight || img.height || 0, alt: (img.alt || '').slice(0, 80) });
  });
  document.querySelectorAll('picture source[srcset]').forEach((s) => add(largest(s.srcset), 'image'));
  document.querySelectorAll('video, audio').forEach((m) => {
    const kind = m.tagName.toLowerCase();
    add(m.currentSrc || m.src, kind);
    m.querySelectorAll('source').forEach((s) => add(s.src, kind));
    if (m.poster) add(m.poster, 'image');
  });
  document.querySelectorAll('a[href]').forEach((a) => {
    if (fileExt.test(a.href)) add(a.href, null);
  });
  document.querySelectorAll('meta[property], meta[name]').forEach((m) => {
    const key = (m.getAttribute('property') || m.getAttribute('name') || '').toLowerCase();
    if (/^(og:image(:url|:secure_url)?|twitter:image(:src)?)$/.test(key)) add(m.content, 'image');
    if (/^(og:video(:url|:secure_url)?|twitter:player:stream)$/.test(key)) add(m.content, 'video');
    if (/^og:audio(:url)?$/.test(key)) add(m.content, 'audio');
  });
  document.querySelectorAll('[style*="background"]').forEach((el) => {
    const m = /url\(["']?([^"')]+)["']?\)/.exec(el.style.backgroundImage || '');
    if (m) add(m[1], 'image');
  });
  return { page: location.href, title: document.title, items: [...items.values()] };
}

async function grabTab(tab) {
  let results = [];
  try {
    results = await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, func: nilouCollectMedia });
  } catch (e) {
    return { ok: false, error: 'This page cannot be scanned (browser pages and the Web Store are off-limits).' };
  }
  const items = new Map();
  for (const r of results) {
    for (const it of (r.result && r.result.items) || []) if (!items.has(it.url)) items.set(it.url, it);
  }
  const hosts = [...new Set([...items.keys()].map((u) => new URL(u).hostname))].slice(0, 40);
  const cookies = {};
  for (const host of hosts) {
    const header = await cookieHeader(`https://${host}/`);
    if (header) cookies[host] = header;
  }
  const res = await callNilou('/grab', { page: tab.url, title: tab.title, items: [...items.values()], cookies });
  return res ? { ok: true, count: items.size } : { ok: false, error: 'Nilou is not running.' };
}

async function sendVideo(url, referrer) {
  return callNilou('/media', { url, referrer: referrer || '', cookieList: await cookieList(url) });
}
