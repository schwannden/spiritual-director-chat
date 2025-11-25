# 我一步步用提示打造屬靈導師 RAG（技術長篇）

我想要的不是「隨便回答」的聊天機器人，而是能像屬靈導師那樣溫柔、帶著 Eugene Peterson 和 Thomas à Kempis 的智慧回應我。以下是我用提示逐步搭出整個系統的過程：從取得原文、切章、建立 Chroma collection，到後端、前端、以及在 Mac 上用 LM Studio 跑 `gpt-oss-20b`（MLX FP4 量化）的故事。

## 從 PDF 到章節 Markdown：提示抽取與切分

起點是一堆 PDF。為了保留原文語氣，我先用 AI 提示請它「逐章抽取原文並轉成 Markdown」，要求附上章名、保持段落與標題，避免亂改文字。拿到初稿後，我再用提示讓 AI「按章切分檔案」，每章成一個 Markdown，方便後面用檔名與 metadata 管理。這比隨機 chunk 好，因為章節本身就是語義單元，RAG 檢索時更少碎片化。

## 用提示寫 Chroma 上傳腳本

當章節都在 `on-living-well/` 底下後，我用提示請 AI 生成 Python 腳本：走訪資料夾、讀取每章 Markdown、呼叫 Chroma 雲端的托管 embedder，把文本、章名、書名一起寫進 collection。於是有了：

- `main.py`：CLI 上傳器，預設上傳《On Living Well》，加 `--collections imitatio-christi` 則上傳《Imitation of Christ》。

我之所以選 Chroma，是因為免費雲額度就夠用，又省掉自架向量庫的維運、備援與安全性麻煩。用提示生成腳本後我再手動微調，確保 metadata（書名、章名）都帶上。

## 後端：提示生成 FastAPI + Chroma 連結

接著我用提示請 AI 幫我起草 FastAPI 伺服器，需求列得很清楚：
- 根據使用者選的書（或兩書都選），到對應的 Chroma collection 取前 n 筆最相似段落。
- 把多書結果合併成單一上下文。
- 組系統提示，要求回應口吻像屬靈導師，並標註來源章節。
- 如果檢索不到內容，要明講不要亂編。

AI 先給我骨架，我再補上 collection 映射、錯誤處理與參數設定，最後形成現在的 `app.py`。在這階段，我同時設定與 LM Studio 的本機 API 端點互動，讓後端把檢索上下文送到本機模型推理。

## 前端：用提示起草，再手改

我讓 AI 先產出一個簡單的 HTML + Tailwind 聊天介面：輸入框、送出按鈕、訊息區。我再加上必要的顏色、留白和滾動行為。前端呼叫 `/chat` API，接收回應後把 Markdown 套進 renderer。這時我發現後端回傳的是 Markdown，而瀏覽器會把它當純文字，所以我又用提示請 AI 幫忙加上 Markdown 解析與簡單樣式，避免標題、引言被扁平化。

## 調整回應格式：提示修正

第一次跑通時，模型回應雜亂，Markdown 頭尾沒對齊。於是我在系統提示加上「用乾淨的 Markdown，包含標題與註腳」的指令，並在前端強制把回應跑過 Markdown 轉 HTML。這個改動也是靠提示反覆要求「格式化回應與來源註記」完成的。

## Persona 分離：再加一個提示迭代

玩了一陣子後，我覺得能分開聽「Peterson 的牧者語氣」和「à Kempis 的修院語氣」會更有趣。於是我在提示裡加上「前端下拉選單決定 persona」，並請 AI 修改前端與後端：
- 前端下拉：選 Peterson、à Kempis，或兩者。
- 後端依選擇決定查哪個 collection，或兩個都查後合併上下文。
- 系統提示會提到「保持所選導師的語氣」，避免混音。

這樣我就可以自由切換單書或雙書，回答中也會標註來源章節，讓聲音清晰。

## 本機推理：LM Studio + MLX FP4

我想離線也能用，所以把 LM Studio 跑在 Mac 上，載入 `openai/gpt-oss-20b` 的 MLX FP4 量化模型。MLX 對 Apple Silicon 有優化，FP4 讓 20B 模型能在 32/64GB RAM 運行。後端只要把檢索上下文與提示 POST 到 LM Studio，本機就能回覆；沒回應時 API 會直說，不會假裝。

## 為什麼這樣的流程有效

1. **逐章切分**：保持語境完整，RAG 檢索更穩定，減少幻覺。
2. **Chroma 雲端**：免費額度足，省維運與安全開銷，專注在內容。
3. **提示驅動開發**：腳本、後端、前端的初稿都用提示產生，再人工微調，加速迭代。
4. **Markdown 保留原味**：回應帶著標題與註腳，讀起來像原典導師。
5. **Persona 切換**：分 collection 與下拉選單，讓導師的聲音更純淨。
6. **本機推理**：隱私、低延遲、離線可用。

## RAG 技術實務與最佳做法

用這個專案為例，我也整理了幾個常見的 RAG 技術選型與實務守則，方便之後擴充或優化：

- **切分策略**：盡量沿著語義邊界（章、節、小節）切，不是固定 token 長度，保留上下文；若不得不切，可以用句號或標題做重疊窗口減少斷裂。
- **Metadata 設計**：寫入 collection 時附上書名、章節、段落位置與 persona 標籤，讓檢索能做過濾、去重與來源呈現；必要時在查詢端做 metadata filter（如選定某位導師）。
- **Embedding/Index**：選擇能表達長文本語義的 embedding 模型，並在 Chroma 內用 HNSW 或 IVF+PQ 之類的近似最近鄰索引；隨資料成長定期重建或調整超參數。
- **檢索管線**：先用語義檢索抓候選，再用 reranker（如 cross-encoder 或本地模型）做重排，提高前段結果品質；top-k 和 context 長度要根據模型上下文與回答格式調校。
- **查詢優化**：可加入 query rewriting（把使用者問題改寫成更檢索友好的查詢）、或混合檢索（BM25 + 向量）來覆蓋關鍵字與語義兩種需求。
- **答案約束**：提示要求「無結果要明講、要標註來源、保持 Markdown 格式」，同時在前端顯示來源章節，降低幻覺風險並提升可追溯性。
- **評估與回饋**：準備一組問題/答案與來源段落，測 retrieval precision/recall、groundedness、citation 正確率；錯誤案例可用來微調切分或 rerank。
- **隱私與佈署**：離線/本機推理保護隱私；雲端資料庫則要設定 API key、網路權限與稽核。備份與版本控管向量資料，避免 collection 損毀或混用。

## 這個專案已做到的 RAG 好做法

- **語義切分到章節**：先抽章、再按章存檔，用章名作 key，天然保留語境，減少碎片幻覺。
- **豐富 metadata**：上傳時把書名、章名一併寫入，後端依 persona 下拉選擇對應 collection，避免聲音混雜。
- **答案來源透明**：系統提示與前端都要求附來源章節，沒有命中時直說不編故事，符合「grounded 回答」原則。
- **格式與體驗一致**：回應用 Markdown 標題、註腳，前端再 render，維持導師語氣與可讀性。
- **本機推理與雲端檢索分工**：Chroma 雲端免維運，LM Studio 本機保隱私並降低延遲，組合出穩定又可離線的體驗。

## 目前用到的提示（Prompts）與設計理由

後端 `app.py` 的關鍵提示現在分成四段，讓模型「溫柔、有根據、長度可控」：

1) **系統 persona + 動態聲線**
```
You are a gentle spiritual director. {voice_for_collections} Give fluent, natural responses that feel personal and prayerful, not like database output. Draw primarily from the provided context passages when available. Always answer in the same language as the most recent user message.
```
- 目的：設定導師語氣，同時依 collections 動態切換（Peterson/à Kempis/混合）；強調自然語感與語言一致性。

2) **上下文約束提示**
```
Use the following excerpts from the book as primary reference material. If they do not address the user question, say so briefly and offer a reflective response grounded in your role as a spiritual director.
```
- 目的：強制引用檢索段落；若無匹配內容先坦白，再給溫和反思，降低幻覺。

3) **語言同步提示**
```
Use the language of the latest user message shown below for your reply. Latest user message: {latest_user}
```
- 目的：在多語對話中鎖定輸出語言，避免歷史訊息混淆。

4) **長度控制提示**
```
Keep the reply focused and around {approx_chars} characters. Prioritize one or two clear insights, avoid repetition, and stop when the main idea is delivered.
```
- 目的：配合前端的 short/medium/long 下拉設定（約 300/500/1000 字元），讓回答長度與場景相符，避免過短或冗長。

這四段提示搭配，讓系統同時做到「口吻與 persona 準確」、「有來源可追」、「語言不跑題」、以及「輸出長度可控」。這符合 RAG 的最佳實務：明確 persona、上下文優先、幻覺處理、語言協調、以及依需求控制輸出長度。

整條管線就是：AI 抽取 PDF → 章節化 Markdown → 提示生成上傳腳本 → Chroma 建 collection → 提示生成後端 API 串 LM Studio → 提示生成前端並加 Markdown renderer → 加 persona 選擇。最後，我得到一個能「請教」導師、帶來源註腳的 RAG，讓科技在旁輕聲提醒，而不是喧鬧主導。***
