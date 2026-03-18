document.addEventListener("DOMContentLoaded", () => {
  const sido = document.querySelector("#regionSido");
  const sigungu = document.querySelector("#regionSigungu");
  const dong = document.querySelector("#regionDong");
  const dongList = document.querySelector("#regionDongList");
  const selectedAddressEl = document.getElementById("requestSelectedAddress");
  const mapStatusEl = document.getElementById("requestMapStatus");
  const mapCanvas = document.getElementById("requestMapCanvas");

  if (!window.REGION_DATA || !sido || !sigungu || !dong || !dongList || !mapCanvas) return;

  const geocodeCache = new Map();
  let requestMap = null;
  let requestMarker = null;
  let debounceTimer = null;

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

  function geocodeAddress(address) {
    return new Promise((resolve, reject) => {
      if (!address) return reject(new Error("주소 없음"));
      if (!window.naver?.maps?.Service) return reject(new Error("지도 API 미설정"));
      if (geocodeCache.has(address)) return resolve(geocodeCache.get(address));

      naver.maps.Service.geocode({ query: address }, (status, response) => {
        if (status !== naver.maps.Service.Status.OK) return reject(new Error("지오코딩 실패"));

        const addresses = response.v2.addresses || [];
        if (!addresses.length) return reject(new Error("검색 결과 없음"));

        const first = addresses[0];
        const result = { lat: parseFloat(first.y), lng: parseFloat(first.x) };
        geocodeCache.set(address, result);
        resolve(result);
      });
    });
  }

  function updateRequestMap() {
    const sidoValue = sido.value.trim();
    const sigunguValue = sigungu.value.trim();
    const address = buildRequestAddress();
    selectedAddressEl.textContent = address || "선택 전";

    if (!sidoValue || !sigunguValue) {
      mapStatusEl.textContent = "시/도와 시/군/구를 먼저 선택해 주세요";
      return;
    }

    geocodeAddress(address)
      .then((point) => {
        mapStatusEl.textContent = "";
        const center = new naver.maps.LatLng(point.lat, point.lng);
        if (!requestMap) {
          requestMap = new naver.maps.Map("requestMapCanvas", { center, zoom: 14 });
          requestMarker = new naver.maps.Marker({ position: center, map: requestMap });
          return;
        }
        requestMap.setCenter(center);
        requestMarker.setPosition(center);
      })
      .catch((error) => {
        mapStatusEl.textContent = error.message === "검색 결과 없음"
          ? "지도 검색 결과가 없습니다"
          : "지도를 불러오지 못했습니다";
      });
  }

  function queueMapUpdate() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(updateRequestMap, 350);
  }

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
});
