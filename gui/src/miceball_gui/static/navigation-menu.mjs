// One explicit expansion owner: hover and focus do not change navigation state.
export function createNavigationMenu(sidebar, toggle, document, unpin) {
  function setOpen(open) {
    const pinned = sidebar.classList.contains('is-pinned');
    sidebar.classList.toggle('is-temporary-expanded', !!open && !pinned);
    toggle.setAttribute('aria-expanded', String(pinned || !!open));
    const label = pinned ? 'Unpin and close navigation' : open ? 'Close navigation' : 'Open navigation';
    toggle.setAttribute('aria-label', label);
    toggle.setAttribute('title', label);
  }
  toggle.addEventListener('click', () => {
    if (sidebar.classList.contains('is-pinned')) unpin();
    else setOpen(!sidebar.classList.contains('is-temporary-expanded'));
  });
  document.addEventListener('pointerdown', event => {
    if (!sidebar.contains(event.target) && !sidebar.classList.contains('is-pinned')) setOpen(false);
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && sidebar.classList.contains('is-temporary-expanded')) {
      setOpen(false); toggle.focus();
    }
  });
  setOpen(false);
  return { close: () => setOpen(false), syncPinned: () => setOpen(false) };
}
