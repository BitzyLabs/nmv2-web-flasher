import { Zap, Wifi, Cpu } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export default function Features() {
  const { t } = useTranslation();

  return (
    <section id="features" className="band-light w-full py-6 md:py-8">
      <div className="mx-auto w-full max-w-screen-xl px-4 md:px-6">
        <div className="mb-4 text-center">
          <p className="brand-kicker">Why the browser</p>
          <h2 className="font-display mt-1 text-2xl font-bold tracking-tight text-[var(--color-ink)]">
            {t('features.title')}
          </h2>
        </div>

        <div className="grid gap-2.5 md:grid-cols-3">
          <FeatureCard
            icon={<Zap className="h-6 w-6" />}
            title={t('features.fastFlashing.title')}
            description={t('features.fastFlashing.description')}
          />
          <FeatureCard
            icon={<Wifi className="h-6 w-6" />}
            title={t('features.webBased.title')}
            description={t('features.webBased.description')}
          />
          <FeatureCard
            icon={<Cpu className="h-6 w-6" />}
            title={t('features.multipleBoards.title')}
            description={t('features.multipleBoards.description')}
          />
        </div>
      </div>
    </section>
  );
}

function FeatureCard({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="rounded-xl border border-[var(--color-hairline-light)] bg-[var(--color-panel)] p-3">
      <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--color-bitzy)] text-[var(--color-gold-ink)]">
        {icon}
      </div>
      <h3 className="font-display mt-2.5 font-bold tracking-tight text-[var(--color-ink)]">
        {title}
      </h3>
      <p className="mt-1 text-sm leading-relaxed text-[var(--color-ink)]/60">{description}</p>
    </div>
  );
}
