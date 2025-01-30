import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface DeviceModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function DeviceModal({ isOpen, onClose }: DeviceModalProps) {
  const { t } = useTranslation();
  const steps = [1, 2, 3, 4, 5, 6, 7];

  return (
    <div
      className={`fixed top-[5vh] left-0 max-h-[85vh] w-full lg:w-5/6 px-4 overflow-scroll bg-white dark:bg-gray-800 p-4 shadow-lg transform ${
        isOpen ? 'lg:translate-x-[10%]' : '-translate-x-full'
      } transition-transform duration-300 ease-in-out rounded-lg`}
    >
      <button
        className="absolute top-4 right-4 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
        onClick={onClose}
      >
        <X className="h-6 w-6" />
      </button>
      <h2 className="text-xl font-bold mb-4">{t('instructions.title')}</h2>
      <ol className="list-decimal list-inside space-y-2 text-sm">
        {steps.map((step) => (
          <li key={step}>{t(`instructions.steps.${step}`)}</li>
        ))}
      </ol>
      <ol className="list-decimal list-inside space-y-2 text-sm">
        {steps.map((step) => (
          <li key={step}>{t(`instructions.steps.${step}`)}</li>
        ))}
      </ol>
      <ol className="list-decimal list-inside space-y-2 text-sm">
        {steps.map((step) => (
          <li key={step}>{t(`instructions.steps.${step}`)}</li>
        ))}
      </ol>
      <ol className="list-decimal list-inside space-y-2 text-sm">
        {steps.map((step) => (
          <li key={step}>{t(`instructions.steps.${step}`)}</li>
        ))}
      </ol>
      <ol className="list-decimal list-inside space-y-2 text-sm">
        {steps.map((step) => (
          <li key={step}>{t(`instructions.steps.${step}`)}</li>
        ))}
      </ol>
      <ol className="list-decimal list-inside space-y-2 text-sm">
        {steps.map((step) => (
          <li key={step}>{t(`instructions.steps.${step}`)}</li>
        ))}
      </ol>
    </div>
  );
}
