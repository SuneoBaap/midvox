import { Toaster as Sonner } from "sonner";

type ToasterProps = React.ComponentProps<typeof Sonner>;

const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      className="toaster group"
      toastOptions={{
        classNames: {
          toast: "group toast group-[.toaster]:bg-[#111111] group-[.toaster]:text-neutral-200 group-[.toaster]:border-[#1A1A1A] group-[.toaster]:shadow-2xl group-[.toaster]:rounded-[6px] group-[.toaster]:p-4",
          description: "group-[.toast]:text-neutral-500 group-[.toast]:text-[11px] group-[.toast]:font-medium",
          actionButton: "group-[.toast]:bg-primary group-[.toast]:text-primary-foreground",
          cancelButton: "group-[.toast]:bg-[#1A1A1A] group-[.toast]:text-neutral-400",
          success: "group-[.toaster]:border-emerald-500/50 group-[.toaster]:bg-emerald-500/5",
          error: "group-[.toaster]:border-red-500/50 group-[.toaster]:bg-red-500/5",
          loading: "group-[.toaster]:border-primary/50 group-[.toaster]:bg-primary/5",
        },
      }}
      {...props}
    />
  );
};

export { Toaster };
