import Link from 'next/link';
import { useTranslation } from 'react-i18next';
import { useTheme } from 'next-themes';
import { ThemeToggle } from './ThemeToggle';
//import LanguageSelector from './LanguageSelector'

const basePath = '';

interface HeaderProps {
  onOpenPanel: () => void;
}

export default function Header({ onOpenPanel }: HeaderProps) {
  const { t } = useTranslation();
  const { theme, setTheme } = useTheme();

  return (
    <header className="h-20 flex items-center justify-between text-bitronics header-custom">
      <div className="px-4 lg:px-6 flex items-center w-full max-w-screen-xl mx-auto">
        {/* Left section */}
        <div className="flex-1">
          <Link className="flex items-baseline " href="#">
            <img
              src={
                theme === 'dark'
                  ? `${basePath}/pictures/bitronics-logo-dark.svg`
                  : `${basePath}/pictures/bitronics-logo-light.svg`
              }
              alt="Bitroics logo"
              style={{ width: '50%' }}
            />
          </Link>
        </div>

        {/* Middle section - centered */}
        <div className="flex-1 flex justify-center">
          <a
            href="https://discord.com/invite/osmu"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:opacity-90 transition-opacity"
          >
            <img
              src="https://dcbadge.limes.pink/api/server/3E8ca2dkcC"
              alt="Discord Server"
              className="h-6 discord-badge"
            />
          </a>
        </div>

        {/* Right section */}
        <div className="flex-1 flex justify-end">
          <nav className="flex items-center gap-4 sm:gap-6">
            <button
              className="text-sm font-medium hover:underline underline-offset-4"
              onClick={onOpenPanel}
            >
              {t('hero.getStarted')}
            </button>
            <Link className="text-sm font-medium hover:underline underline-offset-4" href="#features">
              {t('header.features')}
            </Link>
            <Link
              className="text-sm font-medium hover:underline underline-offset-4"
              href="https://bitronics.store/nerdminer/"
              target="__blank"
            >
              {t('header.shop')}
            </Link>

            {/* <LanguageSelector /> */}
            <ThemeToggle />
          </nav>
        </div>
      </div>
    </header>
  );
}
