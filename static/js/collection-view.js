document.addEventListener("DOMContentLoaded", () => {
  const grid = document.getElementById("collection-grid");
  if (!grid) return;

  const buttons = document.querySelectorAll("[data-collection-view]");
  const storageKey = "spcolle.collectionView";
  const setView = (view) => {
    grid.dataset.view = view === "images" ? "images" : "info";
    buttons.forEach((button) => {
      button.setAttribute(
        "aria-pressed",
        String(button.dataset.collectionView === grid.dataset.view),
      );
    });
  };

  try {
    setView(localStorage.getItem(storageKey));
  } catch {
    setView("info");
  }
  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      setView(button.dataset.collectionView);
      try {
        localStorage.setItem(storageKey, grid.dataset.view);
      } catch {
        // The switch still works when browser storage is unavailable.
      }
    });
  });
});
