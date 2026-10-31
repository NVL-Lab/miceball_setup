// Calendar dates only; service events and recording/audit timestamps are untouched.
export function formatCalendarDate(value) {
  if (typeof value !== 'string') return value;
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value.replaceAll('-', '');
  const legacy = /^([A-Z][a-z]{2}) (\d{1,2}), (\d{4})$/.exec(value);
  const month = legacy && ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'].indexOf(legacy[1]) + 1;
  return month ? `${legacy[3]}${String(month).padStart(2, '0')}${legacy[2].padStart(2, '0')}` : value;
}
