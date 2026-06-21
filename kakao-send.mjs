// kakao-send.mjs - 매일 아침, 오늘의 주요 뉴스를 카카오톡 '나에게 보내기'로 발송
const REST = process.env.KAKAO_REST_KEY;
const REFRESH = process.env.KAKAO_REFRESH_TOKEN;
const SECRET = process.env.KAKAO_CLIENT_SECRET || "";
const SITE = process.env.SITE_URL || "https://newscok.onrender.com";
if (!REST || !REFRESH) { console.error("환경변수 KAKAO_REST_KEY / KAKAO_REFRESH_TOKEN 필요"); process.exit(1); }
const tokBody = { grant_type: "refresh_token", client_id: REST, refresh_token: REFRESH };
if (SECRET) tokBody.client_secret = SECRET;
const tokRes = await fetch("https://kauth.kakao.com/oauth/token", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: new URLSearchParams(tokBody) });
const tok = await tokRes.json();
if (!tok.access_token) { console.error("토큰 갱신 실패:", tok); process.exit(1); }
if (tok.refresh_token) console.log("새 refresh_token:", tok.refresh_token);
const newsRes = await fetch("https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko", { headers: { "User-Agent": "Mozilla/5.0" } });
const xml = await newsRes.text();
const titles = [];
for (const raw of xml.split("<item>").slice(1, 12)) {
  const block = raw.split("</item>")[0];
  let t = (block.match(/<title>([\s\S]*?)<\/title>/) || [])[1] || "";
  const src = (block.match(/<source[^>]*>([\s\S]*?)<\/source>/) || [])[1] || "";
  t = t.replace(/&amp;/g, "&").replace(/&#39;/g, "'").replace(/&quot;/g, '"').replace(/&lt;/g, "<").replace(/&gt;/g, ">").trim();
  if (src && t.endsWith(` - ${src}`)) t = t.slice(0, -(src.length + 3)).trim();
  else t = t.replace(/\s-\s[^-]+$/, "").trim();
  if (t) titles.push(t.length > 34 ? t.slice(0, 33) + "…" : t);
  if (titles.length >= 5) break;
}
const today = new Date().toLocaleDateString("ko-KR", { month: "long", day: "numeric", weekday: "short" });
let text = `📰 ${today} 오늘의 주요 뉴스\n\n` + titles.map((t, i) => `${i + 1}. ${t}`).join("\n");
if (text.length > 195) text = text.slice(0, 193) + "…";
const template = { object_type: "text", text, link: { web_url: SITE, mobile_web_url: SITE }, button_title: "전체 뉴스 보기" };
const sendRes = await fetch("https://kapi.kakao.com/v2/api/talk/memo/default/send", { method: "POST", headers: { Authorization: `Bearer ${tok.access_token}`, "Content-Type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ template_object: JSON.stringify(template) }) });
const sres = await sendRes.json();
if (sendRes.ok && sres.result_code === 0) console.log("✅ 카카오톡 발송 성공!");
else { console.error("발송 실패:", sres); process.exit(1); }
