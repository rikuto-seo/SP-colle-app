document.addEventListener("DOMContentLoaded", () => {
  const root = document.getElementById("qr-check");
  if (!root) return;
  const start = document.getElementById("qr-start");
  const chooseFile = document.getElementById("qr-file-button");
  const fileInput = document.getElementById("qr-file");
  const camera = document.getElementById("qr-camera");
  const video = document.getElementById("qr-video");
  const status = document.getElementById("qr-status");
  const error = document.getElementById("qr-error");
  const results = document.getElementById("qr-results");
  const urlForm = document.getElementById("qr-url-form");
  const login = document.getElementById("qr-login");
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d", { willReadFrequently: true });
  let stream = null;
  let frame = 0;
  let cameraVersion = 0;
  let busy = false;
  let lastScan = 0;
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  };
  function setBusy(value) {
    busy = value;
    start.disabled = value;
    chooseFile.disabled = value;
    urlForm.querySelector("button").disabled = value;
  }
  function stopCamera() {
    cameraVersion += 1;
    cancelAnimationFrame(frame);
    if (stream) stream.getTracks().forEach((track) => track.stop());
    stream = null;
    video.srcObject = null;
    camera.hidden = true;
    if (!busy) start.disabled = false;
  }
  function clearMessage() {
    error.textContent = "";
    login.hidden = true;
    results.hidden = true;
  }
  function photoRow(photo, side) {
    const row = node("div", "qr-photo");
    if (side) row.append(node("span", "trade-side-tag", side));
    const label = node("div", "qr-photo-label");
    label.append(node("strong", "", photo.member), node("small", "", photo.costume), node("span", "", photo.type));
    row.append(label, node("span", "qr-photo-count", `提供可能 ${photo.available}枚`));
    return row;
  }
  function showResults(data) {
    document.getElementById("qr-result-group").textContent = data.group.name;
    const give = data.i_can_give;
    const receive = data.they_can_give;
    document.getElementById("qr-result-summary").textContent = give.length && receive.length
      ? "お互いの希望に合う写真が見つかりました。"
      : give.length || receive.length
        ? "片方の希望に合う写真が見つかりました。"
        : "今の希望・提供可能枚数では、一致する写真はありませんでした。";
    const lists = document.getElementById("qr-result-lists");
    lists.replaceChildren();
    [["あなたが譲れる写真", give, "相手の希望に合う写真はありません。"],
      ["あなたが受け取れる写真", receive, "あなたの希望に合う写真はありません。"]].forEach(([title, photos, empty]) => {
      const section = node("section", "qr-matches");
      section.append(node("h3", "", `${title} · ${photos.length}種類`));
      if (photos.length) photos.forEach((photo) => section.append(photoRow(photo)));
      else section.append(node("p", "small text-muted mb-0", empty));
      lists.append(section);
    });
    const pairs = document.getElementById("qr-pairs");
    pairs.replaceChildren();
    data.mutual.forEach((pair) => {
      const card = node("article", "qr-pair");
      const arrow = node("div", "qr-pair-arrow", "⇅");
      arrow.setAttribute("aria-label", "交換候補");
      card.append(photoRow(pair.give, "譲"), arrow, photoRow(pair.receive, "求"));
      pairs.append(card);
    });
    const total = data.mutual_total ?? data.mutual.length;
    document.getElementById("qr-pair-count").textContent = total
      ? `${total}組の候補${total > data.mutual.length ? `のうち${data.mutual.length}組を表示` : ""}。枚数や条件は相手と相談してください。`
      : "お互いに譲れる写真があると、ここに交換候補が表示されます。";
    results.hidden = false;
    results.focus({ preventScroll: true });
    results.scrollIntoView({ block: "start", behavior: "auto" });
  }
  async function checkUrl(value) {
    if (busy) return;
    stopCamera();
    clearMessage();
    results.hidden = true;
    setBusy(true);
    status.textContent = "交換できる写真を確認しています…";
    try {
      const response = await fetch(root.dataset.checkUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": document.querySelector('meta[name="csrf-token"]').content },
        body: JSON.stringify({ url: value }),
      });
      if (response.status === 401) {
        login.hidden = false;
        throw new Error("ログインの有効期限が切れました。ログインし直してお試しください。");
      }
      if (!response.headers.get("content-type")?.includes("application/json")) {
        if (response.status === 400) {
          login.hidden = false;
          throw new Error("ページの有効期限が切れました。ページを開き直すか、ログインし直してお試しください。");
        }
        throw new Error(response.status === 404
          ? "共有先が見つからないか、公開が停止されています。相手に公開設定を確認してもらってください。"
          : "判定できませんでした。ページを開き直してお試しください。");
      }
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "判定できませんでした。共有URLを確認してください。");
      showResults(data);
      status.textContent = "読み取りました。下に判定結果を表示しています。";
    } catch (reason) {
      status.textContent = "";
      error.textContent = reason.message || "通信できませんでした。接続を確認してお試しください。";
    } finally {
      setBusy(false);
    }
  }
  function decode(source, width, height) {
    const scale = Math.min(1, 1600 / Math.max(width, height));
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    context.drawImage(source, 0, 0, canvas.width, canvas.height);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
    return window.jsQR(pixels.data, pixels.width, pixels.height, { inversionAttempts: "attemptBoth" });
  }
  function tick(time, version) {
    if (version !== cameraVersion || !stream) return;
    if (video.readyState >= 2 && video.videoWidth && time - lastScan > 160) {
      lastScan = time;
      try {
        const code = decode(video, video.videoWidth, video.videoHeight);
        if (code?.data) { void checkUrl(code.data); return; }
      } catch {
        stopCamera();
        status.textContent = "";
        error.textContent = "カメラを読み取れませんでした。QR画像か共有URLでお試しください。";
        return;
      }
    }
    frame = requestAnimationFrame((next) => tick(next, version));
  }
  start.addEventListener("click", async () => {
    if (busy) return;
    stopCamera();
    clearMessage();
    if (typeof window.jsQR !== "function" || !context) {
      error.textContent = "読み取り機能を読み込めませんでした。共有URLで判定してください。";
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia || !window.isSecureContext) {
      error.textContent = "この環境ではカメラを使えません。QR画像か共有URLで判定してください。";
      return;
    }
    const version = cameraVersion;
    start.disabled = true;
    camera.hidden = false;
    status.textContent = "カメラの使用を許可し、相手のQRコードを写してください。";
    try {
      const opened = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
      if (version !== cameraVersion || document.hidden) { opened.getTracks().forEach((track) => track.stop()); return; }
      stream = opened;
      video.srcObject = stream;
      await video.play();
      if (version !== cameraVersion) return;
      lastScan = 0;
      frame = requestAnimationFrame((time) => tick(time, version));
    } catch (reason) {
      if (version !== cameraVersion) return;
      stopCamera();
      status.textContent = "";
      error.textContent = reason.name === "NotAllowedError"
        ? "カメラの使用が許可されていません。ブラウザーの設定を確認するか、QR画像を選んでください。"
        : "カメラを起動できませんでした。QR画像か共有URLでお試しください。";
    }
  });
  document.getElementById("qr-stop").addEventListener("click", () => {
    stopCamera();
    status.textContent = "カメラを終了しました。";
  });
  chooseFile.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    fileInput.value = "";
    if (!file || busy) return;
    stopCamera();
    clearMessage();
    if (file.size > 15 * 1024 * 1024) { error.textContent = "15MB以下のQR画像を選んでください。"; return; }
    if (typeof window.jsQR !== "function" || !context) { error.textContent = "読み取り機能を読み込めませんでした。共有URLで判定してください。"; return; }
    setBusy(true);
    status.textContent = "画像のQRコードを読み取っています…";
    const objectUrl = URL.createObjectURL(file);
    try {
      const image = new Image();
      image.src = objectUrl;
      await image.decode();
      const code = decode(image, image.naturalWidth, image.naturalHeight);
      if (!code?.data) throw new Error("QRコードを見つけられませんでした。コード全体が写った画像を選んでください。");
      setBusy(false);
      await checkUrl(code.data);
    } catch (reason) {
      status.textContent = "";
      error.textContent = reason.name === "EncodingError" ? "画像を開けませんでした。別の画像でお試しください。" : reason.message;
    } finally {
      URL.revokeObjectURL(objectUrl);
      setBusy(false);
    }
  });
  urlForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void checkUrl(document.getElementById("qr-url").value.trim());
  });
  window.addEventListener("pagehide", stopCamera);
  document.addEventListener("visibilitychange", () => { if (document.hidden) stopCamera(); });
  status.textContent = "";
  setBusy(false);
});
