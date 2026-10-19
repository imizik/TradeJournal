/** Copy text from a click: the clipboard API where the page is a secure context, otherwise the older copy command. */
export async function copyText(text: string): Promise<boolean> {
  try { if (window.isSecureContext && navigator.clipboard) { await navigator.clipboard.writeText(text); return true; } } catch { /* fall back below */ }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.cssText = "position:fixed;top:0;left:0;opacity:0";
  document.body.appendChild(area);
  area.select();
  let copied = false;
  try { copied = document.execCommand("copy"); } catch { copied = false; }
  area.remove();
  return copied;
}
