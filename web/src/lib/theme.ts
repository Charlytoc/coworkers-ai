import { createTheme, type MantineColorsTuple } from "@mantine/core";

const wine: MantineColorsTuple = [
  "#fdf2f4",
  "#f5d9de",
  "#e8b0bb",
  "#db8596",
  "#cf6177",
  "#c94d67",
  "#c7435e",
  "#b0344e",
  "#9d2c44",
  "#8a2239",
];

/** Neutral warm-dark palette — near-black bg, warm surfaces, no blue undertone */
const dark: MantineColorsTuple = [
  "#C8C6C4", // [0] body text
  "#A8A6A4", // [1] icons
  "#8A8886", // [2] placeholder / subtle
  "#5A5856", // [3] dimmed text
  "#3A3836", // [4] active borders
  "#2E2C2A", // [5] dividers / borders
  "#1E1C1B", // [6] card / paper / sidebar surface
  "#0C0B0A", // [7] page background (near black)
  "#080706", // [8]
  "#040303", // [9]
];

export const theme = createTheme({
  primaryColor: "wine",
  colors: { wine, dark },

  defaultRadius: "md",

  fontFamily:
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif",

  /** Warmer, less blue dark surfaces than Mantine default */
  other: {},

  components: {
    Button: {
      defaultProps: {
        radius: "md",
      },
    },
    Badge: {
      defaultProps: {
        radius: "sm",
      },
    },
    Paper: {
      defaultProps: {
        radius: "md",
      },
    },
    Modal: {
      defaultProps: {
        radius: "lg",
      },
    },
    Card: {
      defaultProps: {
        radius: "md",
      },
    },
    Input: {
      defaultProps: {
        radius: "md",
      },
    },
  },
});
