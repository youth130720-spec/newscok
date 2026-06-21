// videoSource.js - 인기 뉴스 유튜브 채널 영상 + 카테고리 자동 분류
const CHANNELS = [
  { name: "YTN", id: "UChlgI3UHCOnwUGzWzbJ3H5w" },
  { name: "KBS뉴스", id: "UCcQTRi69dsVYHN3exePtZ1A" },
  { name: "SBS뉴스", id: "UCkinYTS9IHqOEwR1Sze2JTw" },
  { name: "MBC뉴스", id: "UCF4Wxdo3inmxP-Y59wXDsFw" },
  { name: "연합뉴스TV", handle: "@yonhapnewstv" },
  { name: "JTBC뉴스", handle: "@jtbcnews" },
  { name: "슈카월드", handle: "@syukaworld" },
  { name: "삼프로TV", handle: "@3protv" },
  { name: "14F", handle: "@14FMBC" },
  { name: "비디오머그", handle: "@VIDEOMUG" },
];
const CAT_KW = {
  "정치": ["대통령","대선","총선","국회","여당","야당","여야","정부","장관","차관","의원","총리","대표","원내대표","위원장","청문회","특검","탄핵","개헌","공천","선거","정상회담","외교","회담","내각","정책","법안","발의","국정감사","국감","당대표","비대위","대통령실","용산","민주당","국민의힘","조국혁신당","개혁신당","이재명","한동훈","윤석열","발언","입장"],
  "경제": ["경제","증시","주가","코스피","코스닥","나스닥","금리","환율","달러","원화","부동산","아파트","집값","전셋값","분양","물가","인플레","수출","수입","무역","관세","실적","반도체","연봉","세금","예산","추경","한국은행","금통위","비트코인","코인","투자","대출","가격"],
  "사회": ["사건","사고","경찰","검찰","법원","재판","구속","화재","사망","부상","범죄","살인","음주운전","마약","교육","수능","학교","날씨","폭우","폭염","한파","태풍","지진","미세먼지","노조","파업","집회","복지","의료","의대","전공의","응급실"],
  "IT·과학": ["AI","인공지능","챗GPT","반도체","과학","우주","로켓","누리호","위성","기술","스마트폰","갤럭시","아이폰","애플","구글","네이버","카카오","전기차","배터리","테슬라","로봇","해킹","보안"],
  "세계": ["미국","중국","일본","러시아","우크라이나","트럼프","바이든","푸틴","시진핑","유럽","영국","프랑스","독일","외신","국제","중동","이스라엘","하마스","이란","가자","북한","김정은","나토","정상회의"],
  "연예": ["배우","가수","아이돌","그룹","영화","드라마","예능","연예","결혼","이혼","열애","컴백","데뷔","콘서트","앨범","뮤지컬","출연","논란","사과"],
  "스포츠": ["축구","야구","농구","배구","골프","손흥민","이강인","김민재","올림픽","월드컵","아시안컵","KBO","프로야구","K리그","MLB","경기","선수","감독","우승","대표팀","국가대표","홈런","승리"],
};
function classify(title) {
  for (const [cat, kws] of Object.entries(CAT_KW)) if (kws.some((k) => title.includes(k))) return cat;
  return "기타";
}
let cache = null, cachedAt = 0;
const TTL = 30 * 60 * 1000;
const idCache = new Map();
function decode(s){ if(!s) return ""; return s.replace(/&amp;/g,"&").replace(/&#39;/g,"'").replace(/&quot;/g,'"').replace(/&lt;/g,"<").replace(/&gt;/g,">").trim(); }
function ago(d){ const t=new Date(d).getTime(); if(!t) return ""; const m=Math.floor((Date.now()-t)/60000); if(m<60) return `${Math.max(1,m)}분 전`; const h=Math.floor(m/60); if(h<24) return `${h}시간 전`; return `${Math.floor(h/24)}일 전`; }
async function resolveId(handle){
  if(idCache.has(handle)) return idCache.get(handle);
  let id=null;
  try{ const res=await fetch(`https://www.youtube.com/${handle}`,{headers:{"User-Agent":"Mozilla/5.0","Accept-Language":"ko"}}); const html=await res.text(); const m=html.match(/"channelId":"(UC[\w-]{22})"/)||html.match(/channel\/(UC[\w-]{22})/); id=m?m[1]:null; }catch(e){}
  idCache.set(handle,id); return id;
}
async function fetchChannel(ch){
  const id = ch.id || (ch.handle ? await resolveId(ch.handle) : null);
  if(!id) throw new Error(`${ch.name} ID없음`);
  const res=await fetch(`https://www.youtube.com/feeds/videos.xml?channel_id=${id}`,{headers:{"User-Agent":"Mozilla/5.0 (newscok)"}});
  if(!res.ok) throw new Error(`${ch.name} ${res.status}`);
  const xml=await res.text(); const out=[];
  for(const raw of xml.split("<entry>").slice(1,8)){
    const b=raw.split("</entry>")[0];
    const vid=(b.match(/<yt:videoId>(.*?)<\/yt:videoId>/)||[])[1];
    const title=decode((b.match(/<title>([\s\S]*?)<\/title>/)||[])[1]||"");
    const published=(b.match(/<published>(.*?)<\/published>/)||[])[1]||"";
    if(!vid||!title) continue;
    out.push({ videoId:vid, title, channel:ch.name, published, ago:ago(published), category:classify(title), thumb:`https://i.ytimg.com/vi/${vid}/hqdefault.jpg`, url:`https://www.youtube.com/watch?v=${vid}` });
  }
  return out;
}
export async function getVideos(){
  if(cache && Date.now()-cachedAt<TTL) return cache;
  const results=await Promise.allSettled(CHANNELS.map(fetchChannel));
  let all=[]; for(const r of results) if(r.status==="fulfilled") all=all.concat(r.value);
  all.sort((a,b)=>new Date(b.published)-new Date(a.published));
  cache=all.slice(0,48); cachedAt=Date.now(); return cache;
}
