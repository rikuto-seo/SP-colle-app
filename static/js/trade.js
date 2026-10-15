document.addEventListener("DOMContentLoaded", () => {
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const option = (value, label) => {
    const element = node("option", "", label);
    element.value = value;
    return element;
  };
  const quantity = (item) => {
    const input = node("input", "form-control trade-quantity");
    input.type = "number";
    input.min = "1";
    input.max = "999";
    input.required = true;
    input.value = item.quantity;
    input.setAttribute("aria-label", `${item.label}の枚数`);
    input.addEventListener("input", () => {
      item.quantity = input.value;
    });
    return input;
  };
  const remove = (callback) => {
    const button = node("button", "btn btn-outline-secondary btn-sm", "削除");
    button.type = "button";
    button.addEventListener("click", callback);
    return button;
  };

  document.querySelectorAll("[data-confirm]").forEach((button) => {
    button.addEventListener("click", (event) => {
      if (!window.confirm(button.dataset.confirm)) event.preventDefault();
    });
  });
  document.querySelectorAll("[data-copy-url]").forEach((button) => {
    button.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(button.dataset.copyUrl);
        button.textContent = "コピーしました";
      } catch {
        const input = node("input", "form-control mt-2");
        input.readOnly = true;
        input.value = button.dataset.copyUrl;
        button.after(input);
        input.select();
      }
    });
  });

  const imageFallbacks = (root) => {
    root.querySelectorAll(".trade-market-media img").forEach((image) => {
      const fallback = () => {
        image.hidden = true;
        image.parentElement.querySelector(".trade-photo-placeholder").hidden =
          false;
        const cut = image.parentElement.querySelector(".trade-photo-cut");
        if (cut) cut.hidden = true;
      };
      image.addEventListener("error", fallback, { once: true });
      if (image.complete && !image.naturalWidth) fallback();
    });
  };
  imageFallbacks(document);

  const feed = document.getElementById("trade-feed");
  const moreLink = document.querySelector("[data-trade-more]");
  if (feed && moreLink) {
    let loading = false;
    const status = document.getElementById("trade-feed-status");
    moreLink.addEventListener("click", async (event) => {
      event.preventDefault();
      if (loading) return;
      loading = true;
      moreLink.setAttribute("aria-disabled", "true");
      feed.setAttribute("aria-busy", "true");
      status.textContent = "読み込み中…";
      try {
        const response = await fetch(moreLink.href);
        if (!response.ok) throw new Error("page unavailable");
        const page = new DOMParser().parseFromString(
          await response.text(),
          "text/html",
        );
        const next = page.getElementById("trade-feed-more");
        if (!next) throw new Error("invalid page");
        const existing = new Set(
          [...feed.querySelectorAll(".trade-listing-card")].map(
            (card) => card.href,
          ),
        );
        const added = [];
        page
          .querySelectorAll("#trade-feed .trade-listing-card")
          .forEach((card) => {
            if (!existing.has(card.href)) {
              const copy = document.importNode(card, true);
              feed.append(copy);
              added.push(copy);
              existing.add(card.href);
            }
          });
        imageFallbacks(feed);
        status.textContent = added.length
          ? `${added.length}件の交換を追加しました`
          : "ここまでの募集を見ました";
        const nextUrl = next.dataset.nextUrl;
        if (nextUrl) moreLink.href = nextUrl;
        else moreLink.remove();
        if (!event.detail && added.length)
          added[0].focus({ preventScroll: true });
      } catch {
        status.textContent = "読み込めませんでした。もう一度お試しください。";
      } finally {
        loading = false;
        moreLink.removeAttribute("aria-disabled");
        feed.removeAttribute("aria-busy");
      }
    });
  }

  const editor = document.getElementById("trade-editor");
  if (typeof TomSelect !== "undefined") {
    ["trade", "picker"].forEach((prefix) => {
      ["member", "costume", "type"].forEach((key) => {
        const select = document.getElementById(`${prefix}-${key}`);
        if (select)
          new TomSelect(select, {
            create: false,
            maxItems: 1,
            closeAfterSelect: true,
            maxOptions: null,
            allowEmptyOption: true,
            sortField: [{ field: "$order", direction: "asc" }],
          });
      });
    });
  }
  const proposal = document.getElementById("trade-proposal");
  const form = editor || proposal;
  if (!form) return;
  const initial = editor
    ? JSON.parse(document.getElementById("trade-initial").textContent)
    : {};
  let offers = Array.isArray(initial.offers) ? initial.offers : [];
  let items = [];
  let pickerTarget = "offer";
  const dialog = document.getElementById("trade-photo-dialog");
  const pickerError = document.getElementById("picker-error");
  const feedback = document.getElementById("trade-feedback");
  let feedbackTimer;
  const error = document.getElementById("editor-error");
  const offerContainer = document.getElementById("editor-offers");
  const itemContainer = document.getElementById("proposal-items");

  const pickerSelects = Object.fromEntries(
    ["member", "costume", "type"].map((key) => [key, document.getElementById(`picker-${key}`)]),
  );
  const setChoices = (select, values, value = "") => {
    if (select.tomselect) {
      const control = select.tomselect;
      control.clear(true);
      control.clearOptions();
      control.addOption([{ value: "", text: "すべて" }, ...values.map((item) => ({ value: String(item.id), text: item.name }))]);
      control.setValue(value, true);
      control.refreshOptions(false);
    } else {
      select.replaceChildren(option("", "すべて"), ...values.map((item) => option(item.id, item.name)));
      select.value = value;
    }
  };

  function openPicker(value) {
    pickerTarget = value;
    pickerError.textContent = "";
    error.textContent = "";
    document.getElementById("picker-q").value = "";
    Object.values(pickerSelects).forEach((select) => setChoices(select, []));
    document.getElementById("trade-picker-title").textContent =
      !editor ? "渡す写真を追加" : value === "offer" ? "譲る写真を追加" : "欲しい写真を追加";
    dialog.showModal();
    loadPhotos(false);
  }
  dialog.querySelector(".trade-dialog-close").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const box = dialog.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)
      dialog.close();
  });
  function added(row) {
    dialog.close();
    clearTimeout(feedbackTimer);
    feedback.hidden = false;
    feedbackTimer = setTimeout(() => { feedback.hidden = true; }, 1500);
    row?.focus({ preventScroll: true });
    row?.scrollIntoView({ block: "center", behavior: "auto" });
  }
  function addButton(label, action) {
    const button = node("button", "trade-add-photo");
    button.type = "button";
    button.setAttribute("aria-label", label);
    const plus = node("span", "trade-add-symbol", "＋");
    plus.setAttribute("aria-hidden", "true");
    button.append(plus, node("span", "", label));
    button.addEventListener("click", action);
    return button;
  }
  function columns(wanted = false) {
    const header = node("div", `trade-row-head ${wanted ? "trade-photo-want" : "trade-photo-offer"}`);
    header.setAttribute("aria-hidden", "true");
    ["名前", "衣装", "種類", "枚数", ...(wanted ? ["希望"] : []), ""].forEach((text) => header.append(node("span", "", text)));
    return header;
  }
  function photoRow(item, id, onRemove, wanted = false) {
    const row = node("div", `trade-photo-row ${wanted ? "trade-photo-want" : "trade-photo-offer"}`);
    row.id = id;
    row.tabIndex = -1;
    const fallback = (item.label || "").split(" / ");
    [["member", "名前", fallback[0]], ["costume", "衣装", fallback[1]], ["type", "種類", fallback[2]]].forEach(([key, label, old]) => {
      const cell = node("span", `trade-cell trade-cell-${key}`, item[key] || old || "—");
      cell.dataset.label = label;
      row.append(cell);
    });
    const amount = node("span", "trade-quantity-field");
    const unit = node("span", "trade-quantity-unit", "枚");
    unit.setAttribute("aria-hidden", "true");
    amount.append(quantity(item), unit);
    row.append(amount);
    if (wanted) {
      const priority = node("select", "form-select trade-priority");
      priority.setAttribute("aria-label", `${item.label}の希望度`);
      priority.append(option("high", "熱望"), option("normal", "希望"), option("low", "緩く希望"));
      priority.value = item.priority || "normal";
      priority.addEventListener("change", () => { item.priority = priority.value; });
      row.append(priority);
    }
    const del = remove(onRemove);
    del.className = "trade-remove-photo";
    del.textContent = "×";
    del.setAttribute("aria-label", `${item.label || "この写真"}を削除`);
    row.append(del);
    return row;
  }
  function sideHeading(side) {
    const heading = node("h3", "trade-side-heading");
    heading.append(node("span", `trade-side-tag ${side === "求" ? "trade-side-want" : ""}`, side));
    return heading;
  }
  function renderOffers() {
    offerContainer.replaceChildren();
    const bundle = document.getElementById("listing-bundle").checked;
    const display = offers.length ? offers : [null];
    display.forEach((offer, index) => {
      const pair = node("section", "trade-edit-pair");
      const give = node("div", "trade-edit-side");
      give.append(sideHeading("譲"), columns());
      if (offer) {
        give.append(photoRow(offer, `trade-offer-${index}`, () => { offers.splice(index, 1); renderOffers(); }));
        const imageLabel = node("label", "form-check trade-image-share");
        const check = node("input", "form-check-input");
        check.type = "checkbox";
        check.checked = offer.share_image === true;
        check.addEventListener("change", () => { offer.share_image = check.checked; });
        imageLabel.append(check, node("span", "form-check-label", "実物画像も公開する（先頭の1枚）"));
        give.append(imageLabel);
      }
      if (index === display.length - 1)
        give.append(addButton("譲る写真を追加", () => openPicker("offer")));
      const connection = node("div", "trade-edit-connector");
      const arrow = node("span", "trade-swap-arrow", "⇅");
      arrow.setAttribute("aria-label", "交換希望");
      connection.append(arrow);
      if (offer && !bundle) {
        const mode = node("select", "form-select trade-want-mode");
        mode.id = `offer-mode-${index}`;
        mode.setAttribute("aria-label", "譲る写真1枚あたりの希望条件");
        mode.append(option("any", "希望のいずれか1つ"), option("all", "希望のすべて"));
        mode.value = offer.want_mode || "any";
        mode.addEventListener("change", () => { offer.want_mode = mode.value; });
        connection.append(mode);
      } else if (bundle) connection.append(node("span", "small text-muted", "セット全体の希望"));
      const want = node("div", "trade-edit-side");
      want.append(sideHeading("求"), columns(true));
      if (offer) {
        if (!Array.isArray(offer.wants)) offer.wants = [];
        offer.wants.forEach((item, wi) => want.append(photoRow(item, `trade-want-${index}-${wi}`, () => {
          offer.wants.splice(wi, 1); renderOffers();
        }, true)));
      }
      const addWant = addButton("欲しい写真を追加", () => openPicker(index));
      addWant.disabled = !offer;
      if (!offer) addWant.title = "先に譲る写真を追加してください";
      want.append(addWant);
      pair.append(give, connection, want);
      offerContainer.append(pair);
    });
  }

  function renderItems() {
    itemContainer.replaceChildren();
    if (items.length) itemContainer.append(columns());
    items.forEach((item, index) => itemContainer.append(photoRow(item, `trade-provide-${index}`, () => {
      items.splice(index, 1); renderItems();
    })));
  }

  let page = 1;
  let requestId = 0;
  const results = document.getElementById("picker-results");
  const status = document.getElementById("picker-status");
  const more = document.getElementById("picker-more");
  function addPhoto(photo) {
    error.textContent = "";
    pickerError.textContent = "";
    const fields = { member: photo.member, costume: photo.costume, type: photo.type };
    if (editor && pickerTarget !== "offer") {
      const offer = offers[pickerTarget];
      if (!offer) return null;
      if (
        offer.photo_id === photo.id ||
        offer.wants.some((want) => want.photo_id === photo.id)
      ) {
        pickerError.textContent = "提供写真と同じ写真、または登録済みの希望です。";
        return null;
      }
      offer.wants.push({
        photo_id: photo.id,
        label: photo.label,
        quantity: 1,
        priority: "normal",
        ...fields,
      });
      renderOffers();
      return document.getElementById(`trade-want-${pickerTarget}-${offer.wants.length - 1}`);
    } else {
      const list = editor ? offers : items;
      if (list.some((entry) => entry.photo_id === photo.id)) {
        pickerError.textContent = "登録済みです。枚数を調整してください。";
        return null;
      }
      list.push({
        photo_id: photo.id,
        label: photo.label,
        quantity: 1,
        want_mode: "any",
        wants: [],
        share_image: false,
        ...fields,
      });
      if (editor) renderOffers();
      else renderItems();
      return document.getElementById(editor ? `trade-offer-${list.length - 1}` : `trade-provide-${list.length - 1}`);
    }
  }

  async function loadPhotos(append) {
    const id = ++requestId;
    const owned = !editor || pickerTarget === "offer";
    if (!append) {
      page = 1;
      results.replaceChildren();
    }
    status.textContent = "写真を読み込み中…";
    results.setAttribute("aria-busy", "true");
    more.hidden = true;
    const url = new URL(form.dataset.pickerUrl, window.location.origin);
    url.searchParams.set("owned", owned ? "1" : "0");
    url.searchParams.set("page", String(page));
    ["q", "member", "costume", "type"].forEach((key) => {
      url.searchParams.set(key, document.getElementById(`picker-${key}`).value);
    });
    try {
      const response = await fetch(url.toString());
      if (
        !response.ok ||
        !response.headers.get("content-type")?.includes("application/json")
      )
        throw new Error();
      const data = await response.json();
      if (id !== requestId) return;
      if (data.options) Object.entries(pickerSelects).forEach(([key, select]) => {
        setChoices(select, data.options[key], data.filters[key]);
      });
      data.items.forEach((photo) => {
        const button = node("button", "trade-picker-photo");
        button.type = "button";
        const label = node("span", "trade-picker-label", photo.label);
        button.append(label, node("span", "trade-picker-add", "追加"));
        if (owned)
          label.append(
            node("small", "text-muted", `取り置き以外 ${photo.available}枚`),
          );
        button.disabled = owned && photo.available < 1;
        button.addEventListener("click", () => {
          const row = addPhoto(photo);
          if (row) added(row);
        });
        results.append(button);
      });
      status.textContent = data.items.length
        ? "写真を押すと追加できます。"
        : owned
          ? "条件に合う所持写真がありません。コレクションに登録すると選べます。"
          : "条件に合う写真がありません。検索条件を変えてください。";
      more.hidden = !data.has_next;
    } catch {
      if (id === requestId)
        status.textContent =
          "写真を読み込めませんでした。写真を探すボタンで再試行してください。";
    } finally {
      if (id === requestId) results.removeAttribute("aria-busy");
    }
  }
  document.getElementById("picker-search").addEventListener("click", () => {
    loadPhotos(false);
  });
  more.addEventListener("click", () => {
    page += 1;
    loadPhotos(true);
  });
  ["member", "costume", "type"].forEach((key) => {
    document.getElementById(`picker-${key}`).addEventListener("change", () => {
      if (key === "member") setChoices(pickerSelects.costume, []);
      if (key !== "type") setChoices(pickerSelects.type, []);
      loadPhotos(false);
    });
  });
  document.getElementById("picker-q").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      loadPhotos(false);
    }
  });
  if (editor) {
    renderOffers();
    document
      .getElementById("listing-bundle")
      .addEventListener("change", renderOffers);
  } else document.getElementById("proposal-add-photo").addEventListener("click", () => openPicker("proposal"));

  form.addEventListener("submit", (event) => {
    error.textContent = "";
    let data;
    if (editor) {
      const bundle = document.getElementById("listing-bundle").checked;
      if (
        !offers.length ||
        (bundle
          ? !offers.some((offer) => offer.wants.length)
          : offers.some((offer) => !offer.wants.length))
      ) {
        event.preventDefault();
        error.textContent =
          "提供写真と、提供写真ごとの希望を選択してください。";
        return;
      }
      data = {
        alias: document.getElementById("listing-alias").value,
        method: document.getElementById("listing-method").value,
        location: document.getElementById("listing-location").value,
        notes: document.getElementById("listing-notes").value,
        bundle,
        offers,
      };
    } else {
      const requested = [...document.querySelectorAll("[data-request-photo]")]
        .filter((input) => Number(input.value) > 0)
        .map((input) => ({
          photo_id: Number(input.dataset.requestPhoto),
          quantity: input.value,
        }));
      if (!requested.length || !items.length) {
        event.preventDefault();
        error.textContent = "受け取る写真の枚数と、渡す写真を選んでください。";
        return;
      }
      data = {
        owner_items: requested,
        applicant_items: items,
        alias: document.getElementById("proposal-alias").value,
        method: document.getElementById("proposal-method").value,
        note: document.getElementById("proposal-note").value,
      };
    }
    document.getElementById("trade-payload").value = JSON.stringify(data);
  });
});
