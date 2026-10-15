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
            maxOptions: 100,
            allowEmptyOption: true,
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
  const target = document.getElementById("picker-target");
  const error = document.getElementById("editor-error");
  const offerContainer = document.getElementById("editor-offers");
  const itemContainer = document.getElementById("proposal-items");

  function renderOffers() {
    const previous = target.value;
    target.replaceChildren(option("offer", "譲：自分の所持写真から追加"));
    offerContainer.replaceChildren();
    offers.forEach((offer, index) => {
      target.append(
        option(String(index), `求：${offer.label}と交換したい写真`),
      );
      const card = node("section", "card mb-2");
      const body = node("div", "card-body");
      const header = node("div", "trade-editor-row");
      header.append(
        node("strong", "trade-item-label", `譲：${offer.label}`),
        quantity(offer),
        remove(() => {
          offers.splice(index, 1);
          renderOffers();
          loadPhotos(false);
        }),
      );
      body.append(header);
      const modeLabel = node(
        "label",
        "form-label mt-3",
        "この提供写真1枚と交換したい内容",
      );
      const mode = node("select", "form-select mb-2");
      mode.id = `offer-mode-${index}`;
      modeLabel.htmlFor = mode.id;
      mode.append(
        option("any", "下の希望写真のいずれか一つ"),
        option("all", "下の希望写真すべて（複数枚・コンプなど）"),
      );
      mode.value = offer.want_mode || "any";
      mode.addEventListener("change", () => {
        offer.want_mode = mode.value;
      });
      mode.disabled = document.getElementById("listing-bundle").checked;
      if (mode.disabled)
        modeLabel.textContent = "セット全体の希望（登録した写真すべて必要）";
      body.append(modeLabel, mode);
      if (!Array.isArray(offer.wants)) offer.wants = [];
      offer.wants.forEach((want, wi) => {
        const row = node("div", "trade-editor-row trade-wanted-row");
        const priority = node("select", "form-select trade-priority");
        priority.setAttribute("aria-label", `${want.label}の希望度`);
        priority.append(
          option("high", "熱望"),
          option("normal", "希望"),
          option("low", "緩く希望"),
        );
        priority.value = want.priority || "normal";
        priority.addEventListener("change", () => {
          want.priority = priority.value;
        });
        row.append(
          node("span", "trade-item-label", `求：${want.label}`),
          quantity(want),
          priority,
          remove(() => {
            offer.wants.splice(wi, 1);
            renderOffers();
          }),
        );
        body.append(row);
      });
      const addWant = node(
        "button",
        "btn btn-outline-primary btn-sm mt-2",
        "この写真の希望を追加",
      );
      addWant.type = "button";
      addWant.addEventListener("click", () => {
        target.value = String(index);
        loadPhotos(false);
        target.scrollIntoView({ block: "center", behavior: "smooth" });
      });
      body.append(addWant);
      const imageLabel = node("label", "form-check mt-3");
      const imageCheck = node("input", "form-check-input");
      imageCheck.type = "checkbox";
      imageCheck.checked = offer.share_image === true;
      imageCheck.addEventListener("change", () => {
        offer.share_image = imageCheck.checked;
      });
      imageLabel.append(
        imageCheck,
        node(
          "span",
          "form-check-label",
          "登録済みの先頭の実物画像をこの募集に公開する（任意）",
        ),
      );
      body.append(imageLabel);
      card.append(body);
      offerContainer.append(card);
    });
    if ([...target.options].some((entry) => entry.value === previous))
      target.value = previous;
  }

  function renderItems() {
    itemContainer.replaceChildren();
    items.forEach((item, index) => {
      const row = node("div", "trade-editor-row");
      row.append(
        node("span", "trade-item-label", item.label),
        quantity(item),
        remove(() => {
          items.splice(index, 1);
          renderItems();
        }),
      );
      itemContainer.append(row);
    });
  }

  let page = 1;
  let requestId = 0;
  const results = document.getElementById("picker-results");
  const status = document.getElementById("picker-status");
  const more = document.getElementById("picker-more");
  function addPhoto(photo) {
    error.textContent = "";
    if (editor && target.value !== "offer") {
      const offer = offers[Number(target.value)];
      if (!offer) return;
      if (
        offer.photo_id === photo.id ||
        offer.wants.some((want) => want.photo_id === photo.id)
      ) {
        error.textContent = "提供写真と同じ写真、または登録済みの希望です。";
        return;
      }
      offer.wants.push({
        photo_id: photo.id,
        label: photo.label,
        quantity: 1,
        priority: "normal",
      });
      renderOffers();
    } else {
      const list = editor ? offers : items;
      if (list.some((entry) => entry.photo_id === photo.id)) {
        error.textContent = "登録済みです。枚数を調整してください。";
        return;
      }
      list.push({
        photo_id: photo.id,
        label: photo.label,
        quantity: 1,
        want_mode: "any",
        wants: [],
        share_image: false,
      });
      if (editor) renderOffers();
      else renderItems();
    }
  }

  async function loadPhotos(append) {
    const id = ++requestId;
    const owned = !editor || target.value === "offer";
    if (!append) {
      page = 1;
      results.replaceChildren();
    }
    status.textContent = "写真を読み込み中…";
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
      data.items.forEach((photo) => {
        const button = node("button", "trade-picker-photo");
        button.type = "button";
        button.append(node("span", "", photo.label));
        if (owned)
          button.append(
            node("small", "text-muted", `取り置き以外 ${photo.available}枚`),
          );
        button.disabled = owned && photo.available < 1;
        button.addEventListener("click", () => {
          addPhoto(photo);
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
    target.addEventListener("change", () => {
      loadPhotos(false);
    });
  }
  loadPhotos(false);

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
