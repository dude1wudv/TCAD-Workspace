const KEY = 'xjtu-lang';

function domainAttr() {
  const host = typeof location !== 'undefined' ? location.hostname : '';
  return host === 'xjtu.shop' || host.endsWith('.xjtu.shop') ? '; Domain=.xjtu.shop' : '';
}

function readCookieLang() {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(/(?:^|; )xjtu-lang=(en|zh)(?:;|$)/);
  return match ? match[1] : null;
}

export function getLang() {
  const fromCookie = readCookieLang();
  if (fromCookie) return fromCookie;
  let legacy = null;
  try {
    legacy = localStorage.getItem(KEY);
  } catch {}
  const lang = legacy === 'zh' ? 'zh' : 'en';
  if (legacy === 'zh' || legacy === 'en') {
    setLang(lang);
  }
  return lang;
}

export function setLang(lang) {
  const normalized = lang === 'zh' ? 'zh' : 'en';
  if (typeof document !== 'undefined') {
    document.cookie = `${KEY}=${normalized}; Path=/; Max-Age=31536000; SameSite=Lax${domainAttr()}`;
  }
  try {
    localStorage.setItem(KEY, normalized);
  } catch {}
  return normalized;
}

export function applyDocumentLang(lang, { title, description } = {}) {
  const normalized = lang === 'zh' ? 'zh' : 'en';
  document.documentElement.lang = normalized === 'zh' ? 'zh-CN' : 'en';
  if (title) document.title = title;
  if (description) {
    document.querySelector('meta[name="description"]')?.setAttribute('content', description);
  }
  return normalized;
}
