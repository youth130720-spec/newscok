// newsSource.js
// 구글 뉴스 RSS(무료·키 불필요)에서 카테고리별 한국어 뉴스를 가져와 파싱·캐시합니다.

const BASE = "https://news.google.com/rss";
const SUFFIX = "hl=ko&gl=KR&ceid=KR:ko";
const topic = (t) => `${BASE}/headlines/section/topic/${t}?${SUFFIX}`;
const search = (q) => `${BASE}/search?q=${encodeURIComponent(q)}&${SUFFIX}`;

// 카테고리 정의 (친근한 라벨 + 이모지 + RSS 주소)
export const CATEGORIES = [
  { key: "top", label: "주요뉴스", emoji: "📰", url: `${BASE}?${SUFFIX}` },
  { key: "politics", label: "정치", emoji: "🏛️", url: search("정치") },
  { key: "economy", label: "경제", emoji: "💰", url: topic("BUSINESS") },
  { key: "society", label: "사회", emoji: "👥", url: search("사회 이슈") },
  { key: "it", label: "IT·과학", emoji: "💻", url: topic("TECHNOLOGY") },
  { key: "world", label: "세계", emoji: "🌏", url: topic("WORLD") },
  { key: "entertain", label: "연예", emoji: "🎬", url: topic("ENTERTAINMENT") },
  { key: "sports", label: "스포츠", emoji: "⚽", url: topic("SPORTS") },
  { key: "health", label: "건강", emoji: "💊", url: topic("HEALTH") },
];

const cache = new Map(); // key -> { items, at }
const TTL = 10 * 60 * 1000; // 10분

function decode(s) {
  if (!s) return "";
  return s
    .replace(/<!\[CDATA\[/g, "").replace(/\]\]>/g, "")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&apos;/g, "'")
    .replace(/&nbsp;/g, " ").replace(/&amp;/g, "&")
    .replace(/<[^>]+>/g, "")
    .trim();
}
function pick(block, tag) {
  const m = block.match(new RegExp(`<${tag}[^>]*>([\\s\\S]*?)</${tag}>`));
  return m ? m[1] : "";
}
function ago(dateStr) {
  const t = new Date(dateStr).getTime();
  if (!t) return "";
  const diff = Date.now() - t;
  const m = Math.floor(diff / 60000);
  if (m < 1) return "방금 전";
  if (m < 60) return `${m}분 전`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}시간 전`;
  const d = Math.floor(h / 24);
  return `${d}일 전`;
}

function parseRss(xml) {
  const blocks = xml.split("<item>").slice(1);
  const items = [];
  for (const raw of blocks) {
    const block = raw.split("</item>")[0];
    let title = decode(pick(block, "title"));
    const link = decode(pick(block, "link"));
    const pubDate = decode(pick(block, "pubDate"));
    const srcM = block.match(/<source[^>]*url="([^"]*)"[^>]*>([\s\S]*?)<\/source>/);
    const sourceUrl = srcM ? srcM[1] : "";
    const source = decode(srcM ? srcM[2] : pick(block, "source"));
    if (!title || !link) continue;
    // 구글 뉴스 제목 끝의 " - 출처" 제거
    if (source && title.endsWith(` - ${source}`)) title = title.slice(0, -(source.length + 3)).trim();
    else title = title.replace(/\s-\s[^-]+$/, "").trim();
    let favicon = "";
    try { if (sourceUrl) favicon = `https://www.google.com/s2/favicons?domain=${new URL(sourceUrl).hostname}&sz=64`; } catch (e) {}
    items.push({ title, link, source: source || "뉴스", sourceUrl, favicon, pubDate, ago: ago(pubDate) });
  }
  return items;
}

async function fetchRss(url) {
  const res = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0 (newscok)" } });
  if (!res.ok) throw new Error(`뉴스 가져오기 오류: ${res.status}`);
  const xml = await res.text();
  return parseRss(xml).slice(0, 40);
}

async function getCached(key, url) {
  const c = cache.get(key);
  if (c && Date.now() - c.at < TTL) return c.items;
  const items = await fetchRss(url);
  cache.set(key, { items, at: Date.now() });
  return items;
}

export async function getNews(catKey) {
  const cat = CATEGORIES.find((c) => c.key === catKey) || CATEGORIES[0];
  return getCached(cat.key, cat.url);
}
export async function searchNews(q) {
  if (!q || !q.trim()) return [];
  return fetchRss(search(q.trim()));
}
export function getCategories() {
  return CATEGORIES.map((c) => ({ key: c.key, label: c.label, emoji: c.emoji }));
}
