document.addEventListener("DOMContentLoaded", () => {
  const sido = document.querySelector("#regionSido");
  const sigungu = document.querySelector("#regionSigungu");
  const dong = document.querySelector("#regionDong");
  const dongList = document.querySelector("#regionDongList");
  const selectedAddressEl = document.getElementById("requestSelectedAddress");
  const mapStatusEl = document.getElementById("requestMapStatus");
  const mapCanvas = document.getElementById("requestMapCanvas");

  if (!window.REGION_DATA || !sido || !sigungu || !dong || !dongList || !mapCanvas) return;

  const polygonData = window.REQUEST_POLYGON_MAP || { regions: {}, viewBox: "0 0 720 860" };
  const regionShapes = new Map();
  let activeShape = null;

  const sidoList = window.REGION_SIDO_ORDER || Object.keys(window.REGION_DATA);
  sidoList.forEach((name) => sido.add(new Option(name, name)));

  function buildRequestAddress() {
    return [sido.value.trim(), sigungu.value.trim(), dong.value.trim()]
      .filter(Boolean)
      .join(" ");
  }

  function renderDong(s, g) {
    dong.value = "";
    dongList.innerHTML = "";

    if (!s || !g) {
      dong.disabled = true;
      return;
    }

    const items = (window.REGION_DONG_DATA?.[s]?.[g]) || [];
    items.forEach((name) => {
      const opt = document.createElement("option");
      opt.value = name;
      dongList.appendChild(opt);
    });

    dong.disabled = false;
  }

  function renderSigungu(s) {
    sigungu.innerHTML = '<option value="">선택</option>';
    const list = window.REGION_DATA[s] || [];
    list.forEach((g) => sigungu.add(new Option(g, g)));
    sigungu.disabled = list.length === 0;
    renderDong("", "");
  }

  function buildPolygonMap() {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", polygonData.viewBox);
    svg.setAttribute("class", "request-polygon-svg");

    Object.entries(polygonData.regions).forEach(([regionName, config]) => {
      const group = document.createElementNS(ns, "g");
      group.setAttribute("data-region", regionName);
      group.setAttribute("class", "request-polygon-group");

      const polygon = document.createElementNS(ns, "polygon");
      polygon.setAttribute("points", config.points);
      polygon.setAttribute("class", "request-polygon-shape");
      polygon.setAttribute("tabindex", "0");
      polygon.setAttribute("role", "button");
      polygon.setAttribute("aria-label", `${regionName} 폴리곤`);

      const centroid = config.points.split(' ').reduce((acc, pair) => {
        const [x, y] = pair.split(',').map(Number);
        acc.x += x;
        acc.y += y;
        acc.count += 1;
        return acc;
      }, { x: 0, y: 0, count: 0 });

      const text = document.createElementNS(ns, "text");
      text.setAttribute("x", String(centroid.count ? centroid.x / centroid.count : 0));
      text.setAttribute("y", String(centroid.count ? centroid.y / centroid.count : 0));
      text.setAttribute("class", "request-polygon-label");
      text.textContent = config.label || regionName;

      group.appendChild(polygon);
      group.appendChild(text);
      svg.appendChild(group);
      regionShapes.set(regionName, group);

      polygon.addEventListener("click", () => focusRegion(regionName));
      polygon.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          focusRegion(regionName);
        }
      });
    });

    mapCanvas.innerHTML = "";
    mapCanvas.appendChild(svg);
  }

  function focusRegion(regionName) {
    if (sido.value !== regionName) {
      sido.value = regionName;
      renderSigungu(regionName);
      queueMapUpdate();
    }
  }

  function setActivePolygon(regionName) {
    if (activeShape) {
      activeShape.classList.remove("is-active");
    }

    const nextShape = regionShapes.get(regionName);
    if (!nextShape) {
      activeShape = null;
      return;
    }

    nextShape.classList.add("is-active");
    activeShape = nextShape;
  }

  function updateRequestMap() {
    const sidoValue = sido.value.trim();
    const sigunguValue = sigungu.value.trim();
    const dongValue = dong.value.trim();
    const address = buildRequestAddress();

    selectedAddressEl.textContent = address || "선택 전";
    setActivePolygon(sidoValue);

    if (!sidoValue) {
      mapStatusEl.textContent = "시/도를 선택하거나 지도에서 권역을 눌러주세요.";
      return;
    }

    if (!sigunguValue) {
      mapStatusEl.textContent = `${sidoValue} 권역이 선택되었습니다. 시/군/구를 고르면 상세 위치 문구가 갱신됩니다.`;
      return;
    }

    mapStatusEl.textContent = dongValue
      ? `${sidoValue} ${sigunguValue} ${dongValue} 권역을 폴리곤 기반으로 미리보고 있습니다.`
      : `${sidoValue} ${sigunguValue} 권역을 폴리곤 기반으로 미리보고 있습니다.`;
  }

  let debounceTimer = null;
  function queueMapUpdate() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(updateRequestMap, 120);
  }

  buildPolygonMap();

  sido.addEventListener("change", () => {
    renderSigungu(sido.value);
    queueMapUpdate();
  });

  sigungu.addEventListener("change", () => {
    renderDong(sido.value, sigungu.value);
    queueMapUpdate();
  });

  dong.addEventListener("input", () => {
    dong.setCustomValidity(/(읍|면|동)$/.test(dong.value.trim()) ? "" : "읍/면/동 단위까지만 입력할 수 있습니다.");
    queueMapUpdate();
  });

  renderSigungu("");
  updateRequestMap();
});
