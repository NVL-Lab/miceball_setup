import { formatCalendarDate } from './calendar-date.mjs';

const setup = document.querySelector('#panel-setup');
const toolbar = document.createElement('div');
toolbar.className = 'setup-disclosures-toolbar';
toolbar.innerHTML = '<button type="button" data-open-setup>Expand All</button><button type="button" data-close-setup>Collapse All</button>';
setup.querySelector('.setup-demo-note').after(toolbar);
for (const card of setup.querySelectorAll('.setup-card')) {
  const heading = card.querySelector('h3');
  if (!heading) continue;
  const disclosure = document.createElement('details'); disclosure.className = 'setup-disclosure'; disclosure.open = true;
  const summary = document.createElement('summary'); summary.append(heading); disclosure.append(summary);
  const body = document.createElement('div'); body.className = 'setup-disclosure-body';
  for (const child of [...card.childNodes]) body.append(child);
  disclosure.append(body); card.append(disclosure);
}
toolbar.addEventListener('click', event => {
  if (!event.target.closest('button')) return;
  setup.querySelectorAll('.setup-disclosure').forEach(section => { section.open = !!event.target.closest('[data-open-setup]'); });
});

// Keep the native calendar picker and ISO input value; display the owner's canonical format alongside it.
function attachDateReadout(input) {
  if (input.dataset.canonicalDate) return;
  input.dataset.canonicalDate = 'true';
  const output = document.createElement('small'); output.className = 'calendar-date-readout';
  output.setAttribute('aria-live', 'polite'); input.after(output);
  const update = () => { output.textContent = `YYYYMMDD: ${formatCalendarDate(input.value) || 'Not set'}`; };
  input.addEventListener('input', update); input.addEventListener('change', update); update();
}
setup.querySelectorAll('input[type="date"]').forEach(attachDateReadout);
const catalogFields = document.querySelector('#catalog-fields');
new MutationObserver(() => catalogFields.querySelectorAll('input[name="date_of_birth"]').forEach(attachDateReadout))
  .observe(catalogFields, { childList: true });
