import { useTranslation } from 'react-i18next';
import ThemeSwitch from './bitzy/ThemeSwitch';
import { Menu, X } from 'lucide-react';
import { useState } from 'react';

const basePath = '';

// The store's own sections, so the flasher reads as another room of the same
// house rather than a tool that happens to share a logo.
const SITE_LINKS = [
  { label: 'Shop', href: 'https://www.bitzylabs.com' },
];

interface HeaderProps {
  onTogglePanel: () => void;
  /** Whether the steps drawer is showing, for aria-expanded on the triggers. */
  panelOpen: boolean;
}

export default function Header({ onTogglePanel, panelOpen }: HeaderProps) {
  const { t } = useTranslation();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <header className="h-20 header-custom">
      <div className="mx-auto flex h-full w-full max-w-screen-xl items-center px-4 lg:px-6">
        {/* The Bitzy Labs + FLASHER lockup */}
        <a
          href="https://flasher.bitzylabs.com"
          className="flex flex-1 items-center gap-3 transition-opacity hover:opacity-80"
        >
          {/* The bar follows the reader's theme, so the wordmark does
              too: the ink one on light, the light one on dark */}
          <img
            src={`${basePath}/pictures/bitzylabs-logo-light.png`}
            alt="Bitzy Labs"
            className="h-8 w-auto object-contain dark:hidden"
          />
          <img
            src={`${basePath}/pictures/bitzylabs-logo-dark.png`}
            alt=""
            aria-hidden="true"
            className="hidden h-8 w-auto object-contain dark:block"
          />
          <span className="brand-badge">Flasher</span>
        </a>

        <nav className="hidden flex-1 items-center justify-center gap-7 md:flex">
          {SITE_LINKS.map((link) => (
            <a
              key={link.label}
              href={link.href}
              target="_blank"
              rel="noopener noreferrer"
              className="text-base font-medium text-[var(--color-muted-warm)] transition-colors hover:text-[var(--color-bitzy)]"
            >
              {link.label}
            </a>
          ))}
          <button
            onClick={onTogglePanel}
            aria-expanded={panelOpen}
            className="text-base font-medium text-[var(--color-muted-warm)] transition-colors hover:text-[var(--color-bitzy)]"
          >
            {t('header.instructions')}
          </button>
        </nav>

        <div className="flex flex-1 items-center justify-end gap-4 sm:gap-5">
          <div className="hidden md:block">
            <ThemeSwitch />
          </div>
          <button
            type="button"
            onClick={() => setMenuOpen((open) => !open)}
            aria-expanded={menuOpen}
            aria-label={menuOpen ? 'Close menu' : 'Open menu'}
            className="rounded-lg p-2 text-[var(--color-muted-warm)] transition-colors hover:text-[var(--color-bitzy)] md:hidden"
          >
            {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
        </div>
      </div>
      {menuOpen && (
        <div className="absolute inset-x-0 top-full border-b border-[var(--color-hairline-light)] bg-[var(--color-panel)] px-4 pb-4 pt-2 shadow-lg md:hidden">
          <nav className="flex flex-col items-stretch gap-1">
            {SITE_LINKS.map((link) => (
              <a
                key={link.label}
                href={link.href}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => setMenuOpen(false)}
                className="rounded-lg px-3 py-2.5 text-sm font-medium text-[var(--color-muted-warm)] transition-colors hover:bg-black/5 hover:text-[var(--color-bitzy)]"
              >
                {link.label}
              </a>
            ))}
            <button
              type="button"
              onClick={() => {
                setMenuOpen(false);
                onTogglePanel();
              }}
              aria-expanded={panelOpen}
              className="rounded-lg px-3 py-2.5 text-left text-sm font-medium text-[var(--color-muted-warm)] transition-colors hover:bg-black/5 hover:text-[var(--color-bitzy)]"
            >
              {t('header.instructions')}
            </button>
          </nav>
          <div className="mt-2 flex justify-center border-t border-[var(--color-hairline-light)] pt-3">
            <ThemeSwitch />
          </div>
        </div>
      )}
    </header>
  );
}
