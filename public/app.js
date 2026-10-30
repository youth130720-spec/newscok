// app.js - 뉴스콕 (매거진형)
const $ = (s) => document.querySelector(s);
const els = {
  catTabs: $("#catTabs"), newsList: $("#newsList"), listTitle: $("#listTitle"),
  emptyMsg: $("#emptyMsg"), loading: $("#loading"), backBtn: $("#backBtn"),
  searchInput: $("#searchInput"), searchBtn: $("#searchBtn"),
  savedBtn: $("#savedBtn"), savedCount: $("#savedCount"),
  toast: $("#toast"), homeLink: $("#homeLink"),
  vlightbox: $("#vlightbox"), vlbPlayer: $("#vlbPlayer"), vlbClose: $("#vlbClose"),
};
let toastTimer;
function toast(m){ els.toast.textContent=m; els.toast.classList.remove("hidden"); clearTimeout(toastTimer); toastTimer=setTimeout(()=>els.toast.classList.add("hidden"),2400); }
function showLoading(on){ els.loading.classList.toggle("hidden",!on); }
async function api(p,o){ const r=await fetch(p,o); if(!r.ok){ const e=await r.json().catch(()=>({})); throw new Error(e.error||"문제가 발생했어요."); } return r.json(); }

const CAT = {}; // key -> {label,emoji,color}
const CAT_COLOR = { top:"#2f6fed", politics:"#7048e8", economy:"#0ca678", society:"#f76707", it:"#1098ad", world:"#4263eb", entertain:"#e8590c", sports:"#2b8a3e", health:"#e64980" };
const savedUrls = new Set();
let activeCat = "top";
let curEmoji = "📰", curColor = "#2f6fed";

async function init(){
  try{
    const [cats, saved] = await Promise.all([ api("/api/categories"), api("/api/saved").catch(()=>[]) ]);
    saved.forEach((s)=>savedUrls.add(s.url)); updateSavedCount();
    cats.forEach((c)=>{ CAT[c.key]={label:c.label,emoji:c.emoji,color:CAT_COLOR[c.key]||"#2f6fed"}; });
    els.catTabs.innerHTML = `<button class="cat-tab vidtab" data-key="__video">📺 영상뉴스</button>` + cats.map((c,i)=>`<button class="cat-tab ${i===0?"active":""}" data-key="${c.key}">${c.emoji} ${c.label}</button>`).join("");
    els.catTabs.querySelectorAll(".cat-tab").forEach((b)=>b.addEventListener("click",()=>{
      els.catTabs.querySelectorAll(".cat-tab").forEach((x)=>x.classList.toggle("active",x===b));
      els.backBtn.classList.add("hidden");
      if(b.dataset.key==="__video"){ loadVideos(); return; }
      activeCat=b.dataset.key;
      const c=CAT[b.dataset.key]; loadNews(b.dataset.key, `${c.emoji} ${c.label}`);
    }));
    loadNews("top", "📰 주요뉴스");
  }catch(e){ toast("처음 데이터를 불러오지 못했어요: "+e.message); }
}
function updateSavedCount(){ els.savedCount.textContent = savedUrls.size ? `(${savedUrls.size})` : ""; }

function faviImg(n){ return n.favicon ? `<img src="${n.favicon}" alt="" loading="lazy" onerror="this.style.display='none'" />` : ""; }
function featuredHtml(n){
  return `<div class="featured" style="--c:${curColor}" data-link="${n.link}">
    <span class="fbig">${curEmoji}</span>
    <span class="fbadge">🔥 지금 톱기사</span>
    <div class="fcontent">
      <h3>${n.title}</h3>
      <div class="fmeta">${faviImg(n)}<span>${n.source}</span>${n.ago?`<span>· ${n.ago}</span>`:""}</div>
    </div>
  </div>`;
}
function cardHtml(n, rank){
  const saved=savedUrls.has(n.link);
  return `<div class="news-card">
    <div class="nthumb" style="--c:${curColor}"><span>${curEmoji}</span>${rank?`<span class="rank">${rank}</span>`:""}</div>
    <div class="news-body">
      <p class="news-title"><a href="${n.link}" target="_blank" rel="noopener">${n.title}</a></p>
      <div class="news-meta">${faviImg(n)}<span class="src">${n.source}</span>${n.ago?`<span>· ${n.ago}</span>`:""}</div>
    </div>
    <div class="news-actions">
      <button class="pick-btn ${saved?"saved":""}" data-url="${encodeURIComponent(n.link)}" data-title="${encodeURIComponent(n.title)}" data-source="${encodeURIComponent(n.source)}">${saved?"⭐ 담음":"⭐ 담기"}</button>
      <button class="share-btn" data-url="${encodeURIComponent(n.link)}" data-title="${encodeURIComponent(n.title)}">🔗</button>
      <a class="read-link" href="${n.link}" target="_blank" rel="noopener">원문 →</a>
    </div>
  </div>`;
}
function renderList(items){
  if(!items.length){ els.newsList.innerHTML=""; els.emptyMsg.textContent="표시할 뉴스가 없어요. 다른 카테고리나 검색어를 시도해 보세요."; els.emptyMsg.classList.remove("hidden"); return; }
  els.emptyMsg.classList.add("hidden");
  const [first,...rest]=items;
  els.newsList.innerHTML = featuredHtml(first) + rest.map((n,i)=>cardHtml(n, activeCat==="top"?i+2:null)).join("");
  const f=els.newsList.querySelector(".featured"); if(f) f.addEventListener("click",()=>window.open(f.dataset.link,"_blank"));
  bindPick();
}
function bindPick(){ els.newsList.querySelectorAll(".pick-btn").forEach((b)=>b.addEventListener("click",(e)=>{e.stopPropagation();togglePick(b);})); bindShare(); }
function bindShare(){ els.newsList.querySelectorAll(".share-btn").forEach((b)=>b.addEventListener("click",(e)=>{e.stopPropagation();shareItem(decodeURIComponent(b.dataset.url),decodeURIComponent(b.dataset.title));})); }
function shareItem(url,title){
  if(navigator.share){ navigator.share({title:title,text:title,url:url}).catch(()=>{}); }
  else { navigator.clipboard.writeText(url).then(()=>toast("링크를 복사했어요! 붙여넣어 공유하세요."),()=>toast(url)); }
}
async function togglePick(b){
  const url=decodeURIComponent(b.dataset.url), title=decodeURIComponent(b.dataset.title), source=decodeURIComponent(b.dataset.source);
  try{
    if(savedUrls.has(url)){ await api(`/api/saved?url=${encodeURIComponent(url)}`,{method:"DELETE"}); savedUrls.delete(url); b.classList.remove("saved"); b.textContent="⭐ 담기"; toast("보관함에서 뺐어요."); }
    else{ await api("/api/saved",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url,title,source,category:activeCat})}); savedUrls.add(url); b.classList.add("saved"); b.textContent="⭐ 담음"; toast("⭐ 제작 후보에 담았어요!"); }
    updateSavedCount();
  }catch(e){ toast(e.message); }
}

async function loadNews(cat,label){
  const c=CAT[cat]||{emoji:"📰",color:"#2f6fed"}; curEmoji=c.emoji; curColor=c.color;
  els.listTitle.textContent=label||"뉴스"; els.newsList.innerHTML=""; els.emptyMsg.classList.add("hidden"); showLoading(true);
  try{ const items=await api(`/api/news?cat=${encodeURIComponent(cat)}`); showLoading(false); renderList(items); window.scrollTo({top:0,behavior:"smooth"}); }
  catch(e){ showLoading(false); toast(e.message); }
}
function doSearch(){
  const q=els.searchInput.value.trim(); if(!q) return toast("검색어를 입력해 주세요.");
  els.catTabs.querySelectorAll(".cat-tab").forEach((x)=>x.classList.remove("active"));
  els.backBtn.classList.remove("hidden"); curEmoji="🔍"; curColor="#495057";
  els.listTitle.textContent=`🔍 '${q}' 검색 결과`; els.newsList.innerHTML=""; els.emptyMsg.classList.add("hidden"); showLoading(true);
  api(`/api/search?q=${encodeURIComponent(q)}`).then((items)=>{ showLoading(false); renderList(items); }).catch((e)=>{ showLoading(false); toast(e.message); });
}
els.searchBtn.addEventListener("click",doSearch);
els.searchInput.addEventListener("keydown",(e)=>{ if(e.key==="Enter") doSearch(); });

els.savedBtn.addEventListener("click", async ()=>{
  els.catTabs.querySelectorAll(".cat-tab").forEach((x)=>x.classList.remove("active"));
  els.backBtn.classList.remove("hidden"); curEmoji="⭐"; curColor="#f59f00";
  els.listTitle.textContent="⭐ 제작 후보 보관함"; els.newsList.innerHTML=""; els.emptyMsg.classList.add("hidden"); showLoading(true);
  try{
    const saved=await api("/api/saved"); showLoading(false);
    savedUrls.clear(); saved.forEach((s)=>savedUrls.add(s.url)); updateSavedCount();
    if(!saved.length){ els.emptyMsg.textContent="아직 담아둔 뉴스가 없어요. 마음에 드는 뉴스에 ⭐를 눌러보세요!"; els.emptyMsg.classList.remove("hidden"); return; }
    const items=saved.map((s)=>({title:s.title||s.url, link:s.url, source:s.source||"뉴스", favicon:"", ago:""}));
    els.newsList.innerHTML = items.map((n)=>cardHtml(n,null)).join("");
    bindPick();
  }catch(e){ showLoading(false); toast(e.message); }
});

function goHome(){
  els.backBtn.classList.add("hidden"); els.searchInput.value="";
  els.catTabs.querySelectorAll(".cat-tab").forEach((x,i)=>x.classList.toggle("active",i===0));
  activeCat="top"; loadNews("top","📰 주요뉴스"); window.scrollTo({top:0,behavior:"smooth"});
}
els.backBtn.addEventListener("click",goHome);
els.homeLink.addEventListener("click",(e)=>{ e.preventDefault(); goHome(); });

// ===== 영상뉴스 =====
let curVideos=[];
const VCAT_ORDER=["전체","정치","경제","사회","IT·과학","세계","연예","스포츠","기타"];
async function loadVideos(){
  activeCat="video";
  els.listTitle.textContent="📺 영상뉴스 · 인기 뉴스 채널";
  els.newsList.innerHTML=""; els.emptyMsg.classList.add("hidden"); showLoading(true);
  try{
    curVideos=await api("/api/videos"); showLoading(false);
    if(!curVideos.length){ els.emptyMsg.textContent="영상을 불러오지 못했어요. 잠시 후 다시 시도해 주세요."; els.emptyMsg.classList.remove("hidden"); return; }
    const present=new Set(curVideos.map(v=>v.category));
    const cats=["전체",...VCAT_ORDER.filter(c=>c!=="전체"&&present.has(c))];
    const chips=`<div class="vcat-bar">`+cats.map((c,i)=>`<button class="vcat-chip ${i===0?"active":""}" data-c="${c}">${c}</button>`).join("")+`</div>`;
    els.newsList.innerHTML = chips + `<div class="video-grid" id="vgrid"></div>`;
    els.newsList.querySelectorAll(".vcat-chip").forEach((b)=>b.addEventListener("click",()=>{
      els.newsList.querySelectorAll(".vcat-chip").forEach(x=>x.classList.toggle("active",x===b));
      renderVideoGrid(b.dataset.c);
    }));
    renderVideoGrid("전체");
    window.scrollTo({top:0,behavior:"smooth"});
  }catch(e){ showLoading(false); toast(e.message); }
}
function renderVideoGrid(cat){
  const list = cat==="전체" ? curVideos : curVideos.filter(v=>v.category===cat);
  const grid=document.getElementById("vgrid");
  grid.innerHTML = list.map(videoCardHtml).join("");
  grid.querySelectorAll(".vid-thumb").forEach((t)=>t.addEventListener("click",()=>openVideo(t.dataset.id)));
  bindPick();
}
function videoCardHtml(v){
  const saved=savedUrls.has(v.url);
  return `<div class="vid-card">
    <div class="vid-thumb" data-id="${v.videoId}">
      <img src="${v.thumb}" alt="${v.title}" loading="lazy" onerror="this.style.opacity=0" />
      <span class="vid-play">▶</span>
    </div>
    <div class="vid-info">
      <p class="vid-title">${v.title}</p>
      <div class="news-meta"><span class="src">📺 ${v.channel}</span>${v.category&&v.category!=="기타"?`<span class="vcat-tag">${v.category}</span>`:""}${v.ago?`<span>· ${v.ago}</span>`:""}</div>
      <button class="pick-btn ${saved?"saved":""}" data-url="${encodeURIComponent(v.url)}" data-title="${encodeURIComponent(v.title)}" data-source="${encodeURIComponent(v.channel)}">${saved?"⭐ 담음":"⭐ 담기"}</button>
      <button class="share-btn" data-url="${encodeURIComponent(v.url)}" data-title="${encodeURIComponent(v.title)}">🔗 공유</button>
    </div>
  </div>`;
}
function openVideo(id){
  els.vlbPlayer.innerHTML = `<iframe src="https://www.youtube.com/embed/${id}?autoplay=1&rel=0" allow="autoplay; encrypted-media; fullscreen" allowfullscreen></iframe>`;
  els.vlightbox.classList.remove("hidden");
}
function closeVideo(){ els.vlbPlayer.innerHTML=""; els.vlightbox.classList.add("hidden"); }
els.vlbClose.addEventListener("click", closeVideo);
els.vlightbox.addEventListener("click",(e)=>{ if(e.target===els.vlightbox) closeVideo(); });

(function setToday(){ const el=document.getElementById("todayDate"); if(el) el.textContent="📅 "+new Date().toLocaleDateString("ko-KR",{year:"numeric",month:"long",day:"numeric",weekday:"long"})+" 뉴스"; })();
init();
