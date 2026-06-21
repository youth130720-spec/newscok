// db.js - 제작 후보 보관함 저장 (Turso, 없으면 로컬 파일)
import { createClient } from "@libsql/client";

const url = process.env.TURSO_DATABASE_URL;
const authToken = process.env.TURSO_AUTH_TOKEN;
let usingTurso = false;
let client;
if (url && authToken) {
  client = createClient({ url, authToken });
  usingTurso = true;
  console.log("✅ Turso 데이터베이스에 연결했습니다.");
} else {
  client = createClient({ url: "file:local.db" });
  console.log("ℹ️  Turso 정보가 없어 로컬 파일(local.db)을 사용합니다. (임시)");
}
export const isTurso = usingTurso;

export async function initDb() {
  await client.execute(`
    CREATE TABLE IF NOT EXISTS saved_news (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      url TEXT NOT NULL UNIQUE,
      title TEXT,
      source TEXT,
      category TEXT,
      created_at TEXT DEFAULT (datetime('now'))
    )
  `);
}
export async function addSaved({ url, title, source, category }) {
  await client.execute({
    sql: `INSERT OR IGNORE INTO saved_news (url, title, source, category) VALUES (?, ?, ?, ?)`,
    args: [url, title, source, category],
  });
}
export async function removeSaved(url) {
  await client.execute({ sql: `DELETE FROM saved_news WHERE url = ?`, args: [url] });
}
export async function getSaved() {
  const res = await client.execute(`SELECT * FROM saved_news ORDER BY created_at DESC`);
  return res.rows;
}
