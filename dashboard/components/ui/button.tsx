"use client";

import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "relative inline-flex items-center justify-center overflow-hidden whitespace-nowrap rounded-full text-sm font-semibold transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--surface)] disabled:pointer-events-none disabled:opacity-40 active:scale-[0.98]",
  {
    variants: {
      variant: {
        default:
          "bg-primary-light text-[#171A12] shadow-[0_3px_0_rgba(68,80,39,0.14)] hover:-translate-y-0.5 hover:bg-[#BACF7F] hover:shadow-[0_8px_18px_rgba(93,111,50,0.18)]",
        destructive:
          "bg-red-500/90 text-white hover:bg-red-500 shadow-[0_0_16px_rgba(239,68,68,0.3)]",
        outline:
          "border border-[var(--border)] bg-[var(--surface)] text-[var(--ink-muted)] hover:border-primary/50 hover:bg-primary/5 hover:text-[var(--ink)]",
        secondary:
          "border border-[var(--border)] bg-[var(--surface-2)] text-[var(--ink-muted)] hover:bg-primary/10 hover:text-[var(--ink)]",
        ghost:
          "text-[var(--ink-muted)] hover:bg-primary/10 hover:text-[var(--ink)]",
        link:
          "h-auto p-0 text-primary-dark underline-offset-4 hover:underline",
      },
      size: {
        default: "h-10 px-5 py-2",
        sm: "h-8 rounded-lg px-3.5 text-xs",
        lg: "h-12 rounded-xl px-8",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    )
  }
)
Button.displayName = "Button"

export { Button, buttonVariants }
