import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

type SelectorProps = {
  onValueChange: (value: string) => void;
  disabled?: boolean;
  values?: string[];
  placeholder?: string;
  value?: string;
};

export default function BoardVersionSelector({
  onValueChange,
  disabled,
  placeholder = '',
  values = [],
  value,
}: SelectorProps) {
  return (
    <Select 
      onValueChange={onValueChange} 
      disabled={disabled} 
      value={value || undefined}
      key={value || 'empty'}
    >
      <SelectTrigger>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent>
        {values.map((val) => (
          <SelectItem key={val} value={val}>
            {val}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
