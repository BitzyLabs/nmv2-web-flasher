import { useTranslation } from 'react-i18next';
import ThemeSwitch from './bitzy/ThemeSwitch';

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
          <ThemeSwitch />
          <button
            onClick={onTogglePanel}
            aria-expanded={panelOpen}
            className="text-sm font-medium text-[var(--color-muted-warm)] transition-colors hover:text-[var(--color-bitzy)] md:hidden"
          >
            {t('header.instructions')}
          </button>
        </div>
      </div>
    </header>
  );
}
