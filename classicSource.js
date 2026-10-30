// classicSource.js - 명화관: 순풍산부인과 회차별 유튜브 영상 찾기
export const SHOW = { title: "순풍산부인과", start: 7, total: 682 };

const cache = new Map(); // 회차 -> { videoId, title } | null
const TTL_MISS = 60 * 60 * 1000;
const missAt = new Map();

function unescapeJson(s){ try{ return JSON.parse(`"${s}"`); }catch(e){ return s; } }

// 유튜브 검색 결과 페이지에서 영상 ID·제목 뽑기
async function searchYoutube(q){
  const res=await fetch(`https://www.youtube.com/results?search_query=${encodeURIComponent(q)}&hl=ko&gl=KR`,{headers:{"User-Agent":"Mozilla/5.0","Accept-Language":"ko"}});
  if(!res.ok) throw new Error(`유튜브 ${res.status}`);
  const html=await res.text(); const out=[];
  for(const chunk of html.split('"videoRenderer":{"videoId":"').slice(1,25)){
    const vid=chunk.slice(0,11);
    const t=chunk.match(/"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"/);
    if(/^[\w-]{11}$/.test(vid) && t) out.push({ videoId:vid, title:unescapeJson(t[1]) });
  }
  return out;
}
// 제목 속 회차 번호 (예: "순풍산부인과 7회", "EP.7", "7화")
function epNum(title){
  const m=title.match(/(\d{1,3})\s*(?:회|화)/)||title.match(/ep\.?\s*(\d{1,3})/i);
  return m?Number(m[1]):null;
}
export async function getEpisode(n){
  if(cache.has(n)) return cache.get(n);
  if(missAt.has(n) && Date.now()-missAt.get(n)<TTL_MISS) return null;
  const list=await searchYoutube(`${SHOW.title} ${n}회`);
  const hit=list.find((v)=>v.title.includes("순풍")&&epNum(v.title)===n);
  if(!hit){ missAt.set(n,Date.now()); return null; }
  cache.set(n,hit); return hit;
}
