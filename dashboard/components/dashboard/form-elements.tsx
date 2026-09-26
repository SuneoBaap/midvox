import React from "react";
import { Switch } from "@/components/ui/switch";
import { Select, SelectOption } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

// --- ToggleSwitch ---
interface ToggleSwitchProps {
  label?: string;
  description?: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  className?: string;
}

export const ToggleSwitch = ({
  label,
  description,
  checked,
  onCheckedChange,
  disabled,
  className
}: ToggleSwitchProps) => (
  <div className={cn("flex items-center justify-between gap-4 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-4 shadow-sm", className)}>
    {(label || description) && (
      <div className="flex flex-col">
        {label && <span className="text-sm font-medium text-[var(--ink)]">{label}</span>}
        {description && <span className="mt-0.5 text-[11px] text-[var(--ink-muted)]">{description}</span>}
      </div>
    )}
    <Switch checked={checked} onCheckedChange={onCheckedChange} disabled={disabled} />
  </div>
);

// --- DropdownSelect ---
interface DropdownSelectProps {
  label?: string;
  value: string;
  onValueChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
}

export const DropdownSelect = ({
  label,
  value,
  onValueChange,
  options,
  placeholder,
  disabled,
  className
}: DropdownSelectProps) => (
  <div className={cn("space-y-2", className)}>
    {label && <label className="pl-1 text-[10px] font-semibold uppercase tracking-widest text-[var(--ink-muted)]">{label}</label>}
    <Select
      value={value}
      onValueChange={onValueChange}
      options={options}
      placeholder={placeholder}
      disabled={disabled}
    />
  </div>
);

// --- FormInput ---
interface FormInputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  icon?: React.ElementType;
}

export const FormInput = ({ label, icon: Icon, className, ...props }: FormInputProps) => (
  <div className="w-full space-y-2">
    {label && <label className="pl-1 text-[10px] font-semibold uppercase tracking-widest text-[var(--ink-muted)]">{label}</label>}
    <div className="group relative">
      {Icon && (
        <Icon className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--ink-faint)] transition-colors group-focus-within:text-primary" />
      )}
      <Input
        className={cn(
          "rounded-xl focus:ring-primary/15",
          Icon && "pl-10",
          className
        )}
        {...props}
      />
    </div>
  </div>
);
