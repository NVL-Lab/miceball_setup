// Exercise the permanent workspace navigation, not a redundant heading button.
export async function returnFromParameters(page) {
  const origin = await page.evaluate(async () => {
    const {state} = await import(new URL('./protocol-setup.js', document.baseURI));
    return state.parameterContext?.origin || (state.activeSession ? 'session' : 'setup');
  });
  await page.locator(`[data-section="${origin}"]`).click();
}
