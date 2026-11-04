// 화면이 그려지기 전에 테마·글자 크기를 적용(깜빡임 방지). 값은 store/theme.ts와 같다.
// 보안 정책(CSP)이 인라인 스크립트를 막으므로 index.html 안이 아니라 이 파일로 둔다.
(function () {
  try {
    var t = localStorage.getItem("genio.theme") || "system";
    var dark =
      t === "dark" || (t === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
    if (dark) document.documentElement.classList.add("dark");
    if (localStorage.getItem("genio.fontSize") === "large")
      document.documentElement.classList.add("font-large");
  } catch (e) {
    // 저장소를 못 써도 기본 테마로 동작한다
  }
  // 글꼴 CSS는 그리기를 막지 않게 print로 받아 두었다가 다 받으면 화면에 적용한다
  var font = document.getElementById("font-css");
  if (font) {
    var apply = function () {
      font.media = "all";
    };
    if (font.sheet) apply();
    else font.addEventListener("load", apply);
  }
})();
