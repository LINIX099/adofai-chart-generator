(() => {
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const pops = [...document.querySelectorAll(".el-dropdown-menu,.el-popper,[role=menu],[class*=popper],[class*=dropdown]")]
    .filter(visible)
    .map((m) => m.innerText.replace(/\n+/g, " | "))
    .filter((s) => s.trim().length);
  return pops.length ? pops.join("\n---\n") : "（没有可见弹层）";
})()
