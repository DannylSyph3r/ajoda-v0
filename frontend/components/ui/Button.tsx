import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "outline" | "ghost" | "destructive";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      className,
      variant = "primary",
      size = "md",
      loading = false,
      disabled,
      children,
      ...props
    },
    ref,
  ) => {
    // Keyboard focus comes from the global :focus-visible ring (globals.css).
    const variants: Record<string, string> = {
      primary:
        "bg-primary text-white hover:bg-primary-dark active:bg-primary-ink",
      secondary:
        "bg-secondary text-white hover:bg-secondary-dark active:bg-secondary-dark",
      outline:
        "border border-border-strong bg-card text-foreground hover:bg-muted active:bg-border",
      ghost: "text-foreground hover:bg-muted active:bg-border",
      destructive:
        "bg-destructive text-destructive-foreground hover:bg-destructive/90 active:bg-destructive",
    };

    const sizes: Record<string, string> = {
      sm: "text-xs px-3 py-1.5 gap-1.5 rounded-sm",
      md: "text-sm px-4 py-2 gap-2 rounded-sm",
      lg: "text-base px-6 py-2.5 gap-2.5 rounded-sm",
    };

    return (
      <button
        ref={ref}
        disabled={disabled || loading}
        className={cn(
          "inline-flex items-center justify-center font-semibold transition-colors",
          "disabled:opacity-50 disabled:cursor-not-allowed",
          variants[variant],
          sizes[size],
          className,
        )}
        {...props}
      >
        {loading && (
          <svg
            className="animate-spin h-4 w-4 shrink-0"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
            />
          </svg>
        )}
        {children}
      </button>
    );
  },
);
Button.displayName = "Button";

export { Button };
