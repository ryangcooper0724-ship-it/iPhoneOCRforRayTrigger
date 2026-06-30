"use strict";

/* ===== 設定（settingsPanelで上書き、localStorageに保存） ===== */
const DEFAULT_CONFIG = {
  url: "http://192.168.4.1/bib",
  token: "change_me_too",
  confirmCount: 3,
  minConfidence: 60, // 0-100 (Tesseract.jsのconfidenceと同じスケール)
  roiW: 0.5,
  roiH: 0.4,
};

function loadConfig() {
  try {
    return { ...DEFAULT_CONFIG, ...JSON.parse(localStorage.getItem("bibScannerConfig") || "{}") };
  } catch {
    return { ...DEFAULT_CONFIG };
  }
}

function saveConfig(cfg) {
  localStorage.setItem("bibScannerConfig", JSON.stringify(cfg));
}

let config = loadConfig();

/* ===== BibStabilizer: PC側 ocr/bib_reader.py の _observe() と同じロジック ===== */
class BibStabilizer {
  constructor(confirmCount, minConfidence) {
    this.confirmCount = Math.max(1, confirmCount);
    this.minConfidence = minConfidence;
    this.lockedCandidate = null;
    this.lastRawValue = null;
    this.streakCount = 0;
  }

  /** 1件の生の認識結果を処理する。新たにロックが確定したときだけその値を返す。 */
  observe(rawValue, confidence) {
    let value = rawValue;
    if (value !== null && confidence < this.minConfidence) {
      value = null;
    }

    if (value === null || value !== this.lastRawValue) {
      this.lastRawValue = value;
      this.streakCount = value !== null ? 1 : 0;
      return null;
    }

    this.streakCount += 1;
    if (this.streakCount >= this.confirmCount && value !== this.lockedCandidate) {
      this.lockedCandidate = value;
      return value;
    }
    return null;
  }
}

/* ===== UI要素 ===== */
const videoEl = document.getElementById("video");
const canvasEl = document.getElementById("captureCanvas");
const roiEl = document.getElementById("roi");
const lockedBibEl = document.getElementById("lockedBib");
const statusMessageEl = document.getElementById("statusMessage");
const settingsBtn = document.getElementById("settingsBtn");
const settingsPanel = document.getElementById("settingsPanel");
const cfgUrl = document.getElementById("cfgUrl");
const cfgToken = document.getElementById("cfgToken");
const cfgConfirmCount = document.getElementById("cfgConfirmCount");
const cfgMinConfidence = document.getElementById("cfgMinConfidence");
const cfgRoiW = document.getElementById("cfgRoiW");
const cfgRoiH = document.getElementById("cfgRoiH");
const cfgSave = document.getElementById("cfgSave");

const BIB_PATTERN = /^\d{1,2}$/;

let stabilizer = new BibStabilizer(config.confirmCount, config.minConfidence);
let worker = null;
let running = false;

function setStatus(message) {
  statusMessageEl.textContent = message;
}

function positionRoi() {
  const w = window.innerWidth * config.roiW;
  const h = window.innerHeight * config.roiH;
  roiEl.style.width = `${w}px`;
  roiEl.style.height = `${h}px`;
  roiEl.style.left = `${(window.innerWidth - w) / 2}px`;
  roiEl.style.top = `${(window.innerHeight - h) / 2}px`;
}

function openSettings() {
  cfgUrl.value = config.url;
  cfgToken.value = config.token;
  cfgConfirmCount.value = config.confirmCount;
  cfgMinConfidence.value = config.minConfidence;
  cfgRoiW.value = config.roiW;
  cfgRoiH.value = config.roiH;
  settingsPanel.classList.add("open");
}

settingsBtn.addEventListener("click", openSettings);
cfgSave.addEventListener("click", () => {
  config = {
    url: cfgUrl.value.trim() || DEFAULT_CONFIG.url,
    token: cfgToken.value.trim(),
    confirmCount: parseInt(cfgConfirmCount.value, 10) || DEFAULT_CONFIG.confirmCount,
    minConfidence: parseFloat(cfgMinConfidence.value) || DEFAULT_CONFIG.minConfidence,
    roiW: parseFloat(cfgRoiW.value) || DEFAULT_CONFIG.roiW,
    roiH: parseFloat(cfgRoiH.value) || DEFAULT_CONFIG.roiH,
  };
  saveConfig(config);
  stabilizer = new BibStabilizer(config.confirmCount, config.minConfidence);
  positionRoi();
  settingsPanel.classList.remove("open");
});

window.addEventListener("resize", positionRoi);

/* ===== カメラ起動 ===== */
async function startCamera() {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: "environment", width: { ideal: 1280 }, height: { ideal: 720 } },
    audio: false,
  });
  videoEl.srcObject = stream;
  await videoEl.play();
  positionRoi();
}

/* ===== ROI部分をcanvasへ切り出し、前処理（グレースケール＋簡易二値化）してから返す ===== */
function captureRoiFrame() {
  const vw = videoEl.videoWidth;
  const vh = videoEl.videoHeight;
  if (!vw || !vh) return null;

  // 画面表示はobject-fit:coverなので、video実サイズ基準でROI比率を換算する
  const roiW = vw * config.roiW;
  const roiH = vh * config.roiH;
  const sx = (vw - roiW) / 2;
  const sy = (vh - roiH) / 2;

  // 文字認識精度を上げるため3倍に拡大して切り出す
  const scale = 3;
  canvasEl.width = roiW * scale;
  canvasEl.height = roiH * scale;
  const ctx = canvasEl.getContext("2d");
  ctx.drawImage(videoEl, sx, sy, roiW, roiH, 0, 0, canvasEl.width, canvasEl.height);

  // グレースケール化＋簡易二値化（Otsuの簡易近似：平均値しきい値）
  const imageData = ctx.getImageData(0, 0, canvasEl.width, canvasEl.height);
  const data = imageData.data;
  let sum = 0;
  const gray = new Uint8ClampedArray(data.length / 4);
  for (let i = 0, j = 0; i < data.length; i += 4, j++) {
    const g = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
    gray[j] = g;
    sum += g;
  }
  const mean = sum / gray.length;
  for (let i = 0, j = 0; i < data.length; i += 4, j++) {
    const v = gray[j] > mean ? 255 : 0;
    data[i] = data[i + 1] = data[i + 2] = v;
  }
  ctx.putImageData(imageData, 0, 0);

  return canvasEl;
}

/* ===== OCR + 安定化 + 送信のメインループ ===== */
async function recognizeLoop() {
  if (!running) return;

  try {
    const frame = captureRoiFrame();
    if (frame) {
      const { data } = await worker.recognize(frame);
      const candidates = (data.words || [])
        .map((w) => ({ text: w.text.trim(), confidence: w.confidence }))
        .filter((w) => BIB_PATTERN.test(w.text));

      let best = null;
      for (const c of candidates) {
        if (best === null || c.confidence > best.confidence) best = c;
      }

      const rawValue = best ? best.text : null;
      const confidence = best ? best.confidence : 0;

      const locked = stabilizer.observe(rawValue, confidence);
      if (locked !== null) {
        lockedBibEl.textContent = `ロック確定: ${locked}`;
        sendToEsp32(locked, confidence);
      } else if (rawValue) {
        setStatus(`認識中: ${rawValue} (信頼度 ${confidence.toFixed(0)})`);
      } else {
        setStatus("認識待機中…");
      }
    }
  } catch (err) {
    setStatus(`認識エラー: ${err.message || err}`);
  }

  setTimeout(recognizeLoop, 150);
}

/* ===== ESP32への送信 ===== */
function sendToEsp32(bib, confidence) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 1500);

  fetch(config.url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Bib-Token": config.token,
    },
    body: JSON.stringify({ bib, confidence, ts: Math.floor(Date.now() / 1000) }),
    signal: controller.signal,
  })
    .then((res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setStatus(`送信しました（${new Date().toLocaleTimeString()}）`);
    })
    .catch((err) => {
      setStatus(`送信失敗: ${err.message || err}（次のロックで再送されます）`);
    })
    .finally(() => clearTimeout(timeoutId));
}

/* ===== 起動 ===== */
async function main() {
  positionRoi();

  setStatus("OCRエンジンを初期化中…（初回はモデル読み込みに時間がかかります）");
  worker = await Tesseract.createWorker("eng", 1, {
    workerPath: "vendor/tesseract/worker.min.js",
    corePath: "vendor/tesseract/tesseract-core-simd.wasm.js",
    langPath: "vendor/tesseract",
    gzip: true,
  });
  await worker.setParameters({
    tessedit_char_whitelist: "0123456789",
    tessedit_pageseg_mode: "7", // 単一行として扱う
  });

  setStatus("カメラを起動しています…");
  await startCamera();

  running = true;
  setStatus("認識待機中…");
  recognizeLoop();
}

main().catch((err) => {
  setStatus(`起動エラー: ${err.message || err}`);
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("service-worker.js").catch(() => {});
  });
}
