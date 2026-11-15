(() => {
  "use strict";
  const form = document.querySelector("#hud-controls");
  const preview = document.querySelector("#game-preview");
  const output = document.querySelector("#scale-output");
  const status = document.querySelector("#hud-status");
  const sceneImage = document.querySelector("#scene-image");
  const scenes = {
    field: {
      src: "assets/hyrule-field.jpg",
      alt: "Earlier native runtime test capture of Link overlooking Hyrule Field",
    },
    village: {
      src: "assets/kakariko.jpg",
      alt: "Earlier native runtime test capture of Link at the entrance to Kakariko Village",
    },
  };

  function render() {
    const data = new FormData(form);
    const position = data.get("position");
    const detail = data.get("detail");
    const size = Number(data.get("size"));
    preview.dataset.position = position;
    preview.dataset.detail = detail;
    preview.style.setProperty("--hud-scale", String(size / 100));
    output.value = `${size}%`;
    document
      .querySelector("#hud-size")
      .setAttribute("aria-valuetext", `${size} percent`);
    status.textContent =
      detail === "off"
        ? "HUD hidden. Choose FPS plus time or Full to show it again."
        : `HUD at ${position.replace("-", " ")}, ${size} percent, ${detail === "compact" ? "FPS plus playtime" : "full detail"}.`;
  }

  function selectScene(key) {
    const scene = scenes[key];
    if (!scene) return;
    sceneImage.src = scene.src;
    sceneImage.alt = scene.alt;
    document.querySelectorAll("[data-scene]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.scene === key));
    });
  }

  form.addEventListener("input", render);
  form.addEventListener("change", render);
  form.addEventListener("reset", () => {
    // The browser restores form defaults after dispatching the reset event.
    requestAnimationFrame(() => {
      render();
      selectScene("field");
    });
  });
  document.querySelectorAll("[data-scene]").forEach((button) => {
    button.addEventListener("click", () => selectScene(button.dataset.scene));
  });
  render();
})();
