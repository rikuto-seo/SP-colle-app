/* Shared navigation. No account or collection state is changed here. */
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".group-card[data-value]").forEach((card) => {
    card.setAttribute("role", "button");
    card.tabIndex = 0;
    card.setAttribute(
      "aria-pressed",
      String(card.classList.contains("active")),
    );
    card.addEventListener("keydown", (event) => {
      if (
        event.target === card &&
        (event.key === "Enter" || event.key === " ")
      ) {
        event.preventDefault();
        card.click();
      }
    });
    card.addEventListener("click", () => {
      document.querySelectorAll(".group-card[data-value]").forEach((item) => {
        item.setAttribute(
          "aria-pressed",
          String(item.classList.contains("active")),
        );
      });
    });
  });
  document.querySelectorAll(".card-item[tabindex]").forEach((card) => {
    card.addEventListener("keydown", (event) => {
      if (
        event.target === card &&
        (event.key === "Enter" || event.key === " ")
      ) {
        event.preventDefault();
        card.click();
      }
    });
  });
  const trigger = document.getElementById("menu-button");
  const drawer = document.getElementById("sidebar");
  const close = document.getElementById("menu-close");
  const backdrop = document.getElementById("sidebar-backdrop");
  if (trigger && drawer && close && backdrop) {
    const setOpen = (open) => {
      drawer.classList.toggle("open", open);
      drawer.inert = !open;
      drawer.setAttribute("aria-hidden", String(!open));
      trigger.setAttribute("aria-expanded", String(open));
      backdrop.hidden = !open;
      document.body.classList.toggle("menu-open", open);
      if (open) close.focus();
      else trigger.focus();
    };
    trigger.addEventListener("click", () =>
      setOpen(!drawer.classList.contains("open")),
    );
    close.addEventListener("click", () => setOpen(false));
    backdrop.addEventListener("click", () => setOpen(false));
    document.addEventListener("keydown", (event) => {
      if (!drawer.classList.contains("open")) return;
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
      }
      if (event.key === "Tab") {
        const focusable = [
          ...drawer.querySelectorAll("a[href], button:not([disabled])"),
        ];
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    });
  }
  const scrollButton = document.getElementById("scrollTopBtn");
  if (scrollButton) {
    const update = () => {
      scrollButton.hidden = window.scrollY < 400;
    };
    window.addEventListener("scroll", update, { passive: true });
    update();
    scrollButton.addEventListener("click", () =>
      window.scrollTo({
        top: 0,
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "instant"
          : "smooth",
      }),
    );
  }
});
