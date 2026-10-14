import { useTranslation } from 'react-i18next';

const basePath = '';

// The store's own sections, so the flasher reads as another room of the same
// house rather than a tool that happens to share a logo.
const SITE_LINKS = [
  { label: 'Shop', href: 'https://www.bitzylabs.com' },
];

interface HeaderProps {
  onOpenPanel: () => void;
}

export default function Header({ onOpenPanel }: HeaderProps) {
  const { t } = useTranslation();

  return (
    <header className="h-20 header-custom">
      <div className="mx-auto flex h-full w-full max-w-screen-xl items-center px-4 lg:px-6">
        {/* The Bitzy Labs + FLASHER lockup */}
        <a
          href="https://www.bitzylabs.com"
          className="flex flex-1 items-center gap-3 transition-opacity hover:opacity-80"
        >
          {/* The bar is always dark, so the wordmark is always the light one */}
          <img
            src={`${basePath}/pictures/bitzylabs-logo-dark.png`}
            alt="Bitzy Labs"
            className="h-8 w-auto object-contain"
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
              className="text-sm font-medium text-white/70 transition-colors hover:text-white"
            >
              {link.label}
            </a>
          ))}
        </nav>

        <div className="flex flex-1 items-center justify-end gap-4 sm:gap-5">
          <button
            onClick={onOpenPanel}
            className="text-sm font-medium text-white/70 transition-colors hover:text-white"
          >
            {t('header.instructions')}
          </button>
        </div>
      </div>
    </header>
  );
}
