import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("App scaffold", () => {
  it("renders the product name", () => {
    render(<App />);
    expect(screen.getByText(/PIT WALL MULTIVERSE/i)).toBeInTheDocument();
  });
});
