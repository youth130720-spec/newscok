// server.js - 뉴스콕 서버
import "dotenv/config";
import express from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { initDb, isTurso, addSaved, removeSaved, getSaved } from "./db.js";
import { getCategories, getNews, searchNews } from "./newsSource.js";
import { getVideos } from "./videoSource.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();
const PORT = process.env.PORT || 3000;
app.use(express.json());
app.use(express.static(path.join(__dirname, "public")));

app.get("/api/categories", (req, res) => res.json(getCategories()));

app.get("/api/news", async (req, res) => {
  try { res.json(await getNews(req.query.cat || "top")); }
  catch (e) { res.status(502).json({ error: "뉴스를 불러오지 못했어요: " + e.message }); }
});

app.get("/api/videos", async (req, res) => {
  try { res.json(await getVideos()); }
  catch (e) { res.status(502).json({ error: "영상을 불러오지 못했어요: " + e.message }); }
});

app.get("/api/search", async (req, res) => {
  try { res.json(await searchNews(req.query.q || "")); }
  catch (e) { res.status(502).json({ error: "검색에 실패했어요: " + e.message }); }
});

// 제작 후보 보관함
app.get("/api/saved", async (req, res) => {
  try { res.json(await getSaved()); }
  catch (e) { res.status(500).json({ error: e.message }); }
});
app.post("/api/saved", async (req, res) => {
  try {
    const { url, title, source, category } = req.body;
    if (!url) return res.status(400).json({ error: "주소가 없어요." });
    await addSaved({ url, title, source, category });
    res.json({ ok: true });
  } catch (e) { res.status(500).json({ error: e.message }); }
});
app.delete("/api/saved", async (req, res) => {
  try { await removeSaved(req.query.url); res.json({ ok: true }); }
  catch (e) { res.status(500).json({ error: e.message }); }
});

app.get("/api/health", (req, res) => res.json({ ok: true, database: isTurso ? "Turso" : "로컬(local.db)" }));

initDb().then(() => {
  app.listen(PORT, () => console.log(`🗞️ 뉴스콕이 켜졌어요!  http://localhost:${PORT}`));
}).catch((err) => { console.error("DB 준비 오류:", err); process.exit(1); });
