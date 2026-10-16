'use client'
import '../i18n/config';

interface I18nProviderProps {
  children: React.ReactNode;
}

export function I18nProvider({ children }: I18nProviderProps) {
  // The old gate held the page back until a client effect fired --
  // honest on the client, but it erased everything from the static
  // export, so a crawler's first look was a titled shell with no
  // content in it. The translations are bundled and initImmediate
  // hands i18next ready before React ever renders, so the children
  // render on the server pass and hydrate untouched.
  return <>{children}</>;
}