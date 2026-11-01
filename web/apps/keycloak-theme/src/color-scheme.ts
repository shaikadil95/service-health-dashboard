const COLOR_SCHEME_QUERY = "(prefers-color-scheme: dark)"

// The shared tokens switch on a `.dark` class (like the shop); the login pages have no toggle and
// simply follow the operating system.
export function followSystemColorScheme(
  root: HTMLElement = document.documentElement
) {
  const media = window.matchMedia(COLOR_SCHEME_QUERY)
  const apply = () => {
    root.classList.toggle("dark", media.matches)
    root.style.colorScheme = media.matches ? "dark" : "light"
  }
  apply()
  media.addEventListener("change", apply)
  return () => media.removeEventListener("change", apply)
}
