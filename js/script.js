// getlocal score
// setlocal score
// count word
// on key tag to show next message/page + tabindex 0(onfocus)

function getId(idName) {
  return document.getElementById(idName);
}

function getCls(clsName) {
  return document.getElementsByClassName(clsName);
}

// move guide
function moveGuide(e) {
  let guide = getId("guide");
  guide.style.left = e.offsetX;
  guide.style.top = e.offsetY;
}
