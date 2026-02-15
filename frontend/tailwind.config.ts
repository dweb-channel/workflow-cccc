import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "#0F172A",
        foreground: "#F8FAFC",
        muted: "#1E293B",
        "muted-foreground": "#94A3B8",
        border: "#334155",
        input: "#334155",
        ring: "#22D3EE",
        primary: "#22D3EE",
        "primary-foreground": "#0F172A",
        secondary: "#1E293B",
        "secondary-foreground": "#F8FAFC",
        accent: "#22D3EE",
        "accent-foreground": "#0F172A",
      },
      borderRadius: {
        lg: "0.75rem",
        md: "0.5rem",
        sm: "0.25rem"
      }
    }
  },
  plugins: []
};

export default config;
